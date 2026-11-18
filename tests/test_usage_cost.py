import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx

from app import app
from usage_cost import current_usage, record_litellm, record_vertex


class UsageCostTests(unittest.IsolatedAsyncioTestCase):
    async def test_progress_and_final_cost_are_request_local(self):
        async def fake_research(state, history):
            if history[-1]["content"] == "First question":
                usage = SimpleNamespace(prompt_tokens=1000, completion_tokens=100,
                                        cache_read_input_tokens=100)
                record_litellm("vertex_ai/gemini-3.5-flash-lite", "global", usage)
                await asyncio.to_thread(record_vertex, "gemini-3.5-flash-lite", {
                    "usageMetadata": {
                        "promptTokenCount": 1000, "candidatesTokenCount": 80,
                        "thoughtsTokenCount": 20, "toolUsePromptTokenCount": 500,
                    }
                }, grounded=True)
                live = await client.get("/progress/" + request_id)
                self.assertEqual(live.json()["model_cost"], {"usd": 0.001073, "partial": False})
                # A possible vision response whose candidate count already includes thoughts.
                record_vertex("gemini-3.5-flash-lite", {"usageMetadata": {
                    "promptTokenCount": 100, "candidatesTokenCount": 20,
                    "thoughtsTokenCount": 5, "totalTokenCount": 120,
                }})
            else:
                record_litellm("vertex_ai/unknown-model", "global", None)
            return {"status": "complete", "response": "Answer"}

        request_id = "0b3064ee-311d-4fe3-9dc9-6684c9944571"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            with patch("app.run_research", side_effect=fake_research):
                first = await client.post("/chat", json={"message": "First question", "request_id": request_id})
                self.assertEqual(first.json()["model_cost"], {"usd": 0.001153, "partial": False})
                second = await client.post("/chat", json={"message": "Next question", "session_id": first.json()["session_id"]})
                self.assertEqual(second.json()["model_cost"], {"usd": None, "partial": True})
        self.assertIsNone(current_usage.get())
