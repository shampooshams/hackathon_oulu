"""LLM backends. Picks Gemini, Claude or OpenAI from the keys in .env.
With no key, the companion falls back to offline templates (see offline.py),
so the demo always works."""
from __future__ import annotations

import os


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
        self.client = genai.Client(api_key=os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
        self.model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        self.name = f"Gemini ({self.model})"

    def generate(self, system: str, messages: list[dict], max_tokens: int = 700) -> str:
        from google.genai import types
        contents = [types.Content(role="model" if m["role"] == "assistant" else "user",
                                  parts=[types.Part(text=m["content"])]) for m in messages]
        config = types.GenerateContentConfig(system_instruction=system, max_output_tokens=max_tokens)
        if "flash" in self.model:  # thinking would use up the answer's token budget
            config.thinking_config = types.ThinkingConfig(thinking_budget=0)
        resp = self.client.models.generate_content(model=self.model, contents=contents, config=config)
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
