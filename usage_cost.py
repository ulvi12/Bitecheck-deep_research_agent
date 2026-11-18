"""Request-local estimates for standard Vertex Gemini model usage."""
from contextvars import ContextVar
from threading import Lock

# USD per million tokens, in input, cached input, and output order.
# https://cloud.google.com/model-garden/pricing
GLOBAL_RATES = {
    "gemini-3.5-flash-lite": (0.30, 0.03, 2.50),
    "gemini-3.5-flash": (1.50, 0.15, 9.00),
}


class UsageCost:
    def __init__(self):
        self._lock = Lock()
        self._usd = 0.0
        self._calls = 0
        self._unpriced = 0

    def add(self, model, location, prompt, cached, output, *, vertex=True):
        rates = GLOBAL_RATES.get(model.removeprefix("vertex_ai/")) if vertex else None
        with self._lock:
            if not rates or not all(type(n) is int and n >= 0 for n in (prompt, cached, output)) or cached > prompt:
                self._unpriced += 1
                return
            regional_factor = 1 if location == "global" else 1.1
            self._usd += regional_factor * ((prompt - cached) * rates[0] + cached * rates[1] + output * rates[2]) / 1_000_000
            self._calls += 1

    def snapshot(self):
        with self._lock:
            return {
                "usd": round(self._usd, 9) if self._calls else None,
                "partial": bool(self._unpriced),
            }


current_usage: ContextVar[UsageCost | None] = ContextVar("current_usage", default=None)


def record_litellm(model, location, usage):
    tracker = current_usage.get()
    if tracker is None:
        return
    details = getattr(usage, "prompt_tokens_details", None)
    cached = getattr(usage, "cache_read_input_tokens", None)
    if cached is None:
        cached = getattr(details, "cached_tokens", 0) or 0
    # LiteLLM already includes Gemini reasoning in completion_tokens.
    tracker.add(model, location, getattr(usage, "prompt_tokens", None), cached,
                getattr(usage, "completion_tokens", None), vertex=model.startswith("vertex_ai/"))


def record_vertex(model, body, *, grounded=False):
    tracker = current_usage.get()
    if tracker is None:
        return
    usage = body.get("usageMetadata") or {}
    prompt = usage.get("promptTokenCount")
    candidates = usage.get("candidatesTokenCount", 0)
    thoughts = usage.get("thoughtsTokenCount", 0)
    tool_input = usage.get("toolUsePromptTokenCount", 0)
    total = usage.get("totalTokenCount")
    if not all(type(value) is int and value >= 0 for value in (prompt, candidates, thoughts, tool_input)):
        tracker.add(model, "global", None, 0, None)
        return
    # Some Gemini responses already include thought tokens in the candidate count.
    output = candidates if prompt + candidates + tool_input == total else candidates + thoughts
    tracker.add(model, "global", prompt + (0 if grounded else tool_input),
                usage.get("cachedContentTokenCount", 0), output)
