"""LLM backends. Picks Gemini, Claude or OpenAI from the keys in .env.
With no key, the companion falls back to offline templates (see offline.py),
so the demo always works."""
from __future__ import annotations

import os
import re

# Tried in order if the chosen Gemini model isn't found or its quota is used up (each model has its own).
GEMINI_BACKUPS = ("gemini-flash-latest", "gemini-3.8-flash", "gemini-3.6-flash", "gemini-2.5-flash")


def explain(e: Exception) -> str:
    """A short, plain reason for an AI error, safe to show (no keys)."""
    msg = str(e)
    code = getattr(e, "code", None) or getattr(e, "status_code", None)
    if "API_KEY_INVALID" in msg or "API key not valid" in msg:
        why = "the API key isn't valid (revoked, or pasted with extra spaces or quotes)"
    elif code == 403 or "PERMISSION_DENIED" in msg:
        why = "the API key isn't allowed to use this model or API"
    elif code == 404 or "NOT_FOUND" in msg:
        why = "the model name wasn't found; check GEMINI_MODEL"
    elif (code == 429 or "RESOURCE_EXHAUSTED" in msg) and re.search(r"limit: 0\b", msg):
        why = "this model has no free quota for your key; try GEMINI_MODEL = \"gemini-2.5-flash\" or turn on billing"
    elif code == 429 or "RESOURCE_EXHAUSTED" in msg:
        why = "the free quota or rate limit is used up; wait a minute or check the plan"
    else:
        why = re.sub(r"\s+", " ", msg)[:160] or "unknown error"
    return f"{type(e).__name__}: {re.sub(r'AIza[0-9A-Za-z_-]{20,}', '[key]', why)}"


def _switchable(e: Exception) -> bool:
    """Model not found, or its quota used up: another model may still work."""
    msg = str(e)
    return getattr(e, "code", None) in (404, 429) or "NOT_FOUND" in msg or "RESOURCE_EXHAUSTED" in msg


class AnthropicBackend:
    def __init__(self):
        import anthropic
        self.client = anthropic.Anthropic()
        self.model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")
        self.name = f"Claude ({self.model})"

    def generate(self, system: str, messages: list[dict], max_tokens: int = 700) -> str:
        resp = self.client.messages.create(model=self.model, max_tokens=max_tokens,
                                           system=system, messages=messages)
        return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()


class OpenAIBackend:
    def __init__(self):
        import openai
        self.client = openai.OpenAI()
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.name = f"OpenAI ({self.model})"

    def generate(self, system: str, messages: list[dict], max_tokens: int = 700) -> str:
        resp = self.client.chat.completions.create(
            model=self.model, max_tokens=max_tokens,
            messages=[{"role": "system", "content": system}] + messages)
        return (resp.choices[0].message.content or "").strip()


class GeminiBackend:
    def __init__(self):
        from google import genai
        key = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip().strip("\"'")
        self.client = genai.Client(api_key=key)
        self.model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip().strip("\"'")
        self.name = f"Gemini ({self.model})"

    def generate(self, system: str, messages: list[dict], max_tokens: int = 700) -> str:
        from google.genai import types
        contents = [types.Content(role="model" if m["role"] == "assistant" else "user",
                                  parts=[types.Part(text=m["content"])]) for m in messages]
        try:
            return self._call(types, system, contents, max_tokens)
        except Exception as e:
            if not _switchable(e):
                raise
            for backup in GEMINI_BACKUPS:  # not found or out of quota: try another model
                if backup == self.model:
                    continue
                try:
                    text = self._call(types, system, contents, max_tokens, backup)
                except Exception:
                    continue
                self.model, self.name = backup, f"Gemini ({backup}, instead of {self.model})"
                return text
            raise

    def _call(self, types, system, contents, max_tokens, model=None) -> str:
        model = model or self.model
        if "flash" in model:  # thinking would use up the answer's token budget
            config = types.GenerateContentConfig(system_instruction=system, max_output_tokens=max_tokens,
                                                 thinking_config=types.ThinkingConfig(thinking_budget=0))
            try:
                resp = self.client.models.generate_content(model=model, contents=contents, config=config)
                return (resp.text or "").strip()
            except Exception as e:  # newer models may not accept switching thinking off: try without it
                if "NOT_FOUND" in str(e) or "API_KEY" in str(e) or getattr(e, "code", None) in (403, 404, 429):
                    raise
        # Pro (and newer) models think first: leave room for the thinking on top of the answer
        plain = types.GenerateContentConfig(system_instruction=system, max_output_tokens=max_tokens + 2048)
        resp = self.client.models.generate_content(model=model, contents=contents, config=plain)
        return (resp.text or "").strip()

def get_backend():
    """Return a backend, or None for offline template mode."""
    try:
        if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
            return GeminiBackend()
        if os.getenv("ANTHROPIC_API_KEY"):
            return AnthropicBackend()
        if os.getenv("OPENAI_API_KEY"):
            return OpenAIBackend()
    except Exception:  # missing package, bad config
        return None
    return None
