"""Cloud Run entrypoint. Keeps Project 1's response/session_id/tool_calls contract."""
from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from agents import MODEL, ModelNotConfigured, RunState, model_configured, run_research
from evidence import EvidenceStore

SUPPORTED_MARKETS = EvidenceStore().catalog()
progress_runs: dict[str, RunState] = {}
APP_NAME = os.getenv("APP_NAME", "BiteCheck")
app = FastAPI(title=APP_NAME)


@dataclass
class Session:
    history: list = field(default_factory=list)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    touched: float = field(default_factory=time.monotonic)


sessions: dict[str, Session] = {}
request_slots = asyncio.Semaphore(4)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=6000)
    session_id: uuid.UUID | None = None
    request_id: uuid.UUID | None = None


class ChatResponse(BaseModel):
    response: str
    session_id: str
    tool_calls: list[dict]
    status: str = "complete"
    sources: list[dict] = Field(default_factory=list)
    comparisons: list[dict] = Field(default_factory=list)
    report: dict | None = None
    elapsed_seconds: float = 0
    search_suggestions: list[str] = Field(default_factory=list)
    activity: dict = Field(default_factory=dict)


class ClearRequest(BaseModel):
    session_id: uuid.UUID


@app.get("/")
async def index():
    return HTMLResponse((Path(__file__).parent / "index.html").read_text(encoding="utf-8"))


@app.get("/health")
async def health():
    return {"status":"ok", "name":APP_NAME, "model":MODEL, "model_configured":await asyncio.to_thread(model_configured),
            "mode":"live", "markets":SUPPORTED_MARKETS}


@app.get("/progress/{request_id}")
async def progress(request_id: uuid.UUID):
    state=progress_runs.get(str(request_id))
    if not state:
        return {"status":"pending", "active_agents":[], "sources_read":0,
                "activity":{"events":[], "active_agents":[], "queued_agents":[]}}
    return {"status":"running", "active_agents":sorted(state.active_agents),
            "sources_read":len(state.read_ids),
            "completed_tools":sum(c["status"]=="complete" for c in state.trace),
            "activity":state.activity_snapshot()}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    message = request.message.strip()
    if not message:
        raise HTTPException(422, "Enter a question first.")
    now = time.monotonic()
    for key, old in list(sessions.items()):
        if now-old.touched > 7200 and not old.lock.locked():
            del sessions[key]
    requested_id = str(request.session_id) if request.session_id else None
    session_id = requested_id if requested_id in sessions else str(uuid.uuid4())
    if session_id not in sessions:
        if len(sessions) >= 100:
            raise HTTPException(503, "The research desk is busy. Try again later.")
        sessions[session_id] = Session()
    session = sessions[session_id]
    if session.lock.locked():
        raise HTTPException(409, "Wait for this conversation's current investigation to finish.")
    state = RunState(EvidenceStore())
    request_id = str(request.request_id or uuid.uuid4())
    async with session.lock:
        if len(session.history) >= 40:
            return ChatResponse(response="Start a new chat to continue; this conversation reached its length limit.", session_id=session_id, tool_calls=[], status="limit")
        progress_runs[request_id] = state
        history = [*session.history, {"role":"user", "content":message}]
        try:
            async with asyncio.timeout(max(30, min(280, int(os.getenv("REQUEST_DEADLINE_SECONDS", "260"))))):
                async with request_slots:
                    result = await run_research(state, history)
            if result["status"] in ("complete", "clarification"):
                session.history = [*history, {"role":"assistant", "content":result["response"]}]
            status_code = 200
        except ModelNotConfigured:
            result = {"response":"Research is not connected to a model yet. Set GOOGLE_CLOUD_PROJECT and authenticate with Google Cloud, or configure a Gemini API key. No research result has been substituted.", "status":"not_configured"}
            status_code = 503
        except TimeoutError:
            result = {"response":"This investigation reached its time limit. Completed tool calls are preserved below; no final conclusion was produced. Try a narrower product or ingredient question.", "status":"timeout"}
            status_code = 504
        except Exception as exc:
            logging.warning("Research failed (%s)", type(exc).__name__)
            result = {"response":"The research could not finish. Completed tool calls are preserved below. Check model access and Google Cloud authentication, then retry; no conclusion has been substituted.", "status":"error"}
            status_code = 502
        finally:
            progress_runs.pop(request_id, None)
        for entry in state.trace:
            if entry["status"] == "running":
                state.finish_call(entry, {"error":"Request ended before this operation completed"}, True)
        session.touched = time.monotonic()
        if requested_id and requested_id != session_id:
            result["response"] = "Your earlier chat expired or the server restarted; this is a new conversation. " + result["response"]
        payload = ChatResponse(**result, session_id=session_id, tool_calls=state.trace, activity=state.activity_snapshot(),
                               elapsed_seconds=round(time.monotonic()-state.started, 2))
        return JSONResponse(status_code=status_code, content=payload.model_dump())


@app.post("/clear")
async def clear(request: ClearRequest):
    session = sessions.get(str(request.session_id))
    if session and session.lock.locked():
        raise HTTPException(409, "Wait for the current investigation to finish.")
    sessions.pop(str(request.session_id), None)
    return {"status":"ok"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8002")))
