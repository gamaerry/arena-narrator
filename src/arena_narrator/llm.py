"""Tiny provider abstraction: send (system, user, json schema) → parsed dict."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from typing import Protocol

DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-5-5",
    "gemini": "gemini-flash-latest",
    "claude-cli": "sonnet",
    "openrouter": "qwen/qwen3.8-27b:free",
}


class LLMError(RuntimeError):
    pass


class LLM(Protocol):
    name: str
    model: str

    def complete_json(self, system: str, user: str, schema: dict) -> dict: ...


def _loads(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


class AnthropicLLM:
    name = "anthropic"

    def __init__(self, model: str | None = None):
        try:
            import anthropic
        except ImportError as e:
            raise LLMError("pip install 'arena-narrator[anthropic]'") from e
        self.client = anthropic.Anthropic()
        self.model = model or DEFAULT_MODELS[self.name]

    def complete_json(self, system: str, user: str, schema: dict) -> dict:
        with self.client.messages.stream(
            model=self.model,
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        ) as stream:
            msg = stream.get_final_message()
        if msg.stop_reason == "refusal":
            raise LLMError("Anthropic API refused the request (stop_reason=refusal)")
        text = "".join(b.text for b in msg.content if b.type == "text")
        try:
            return _loads(text)
        except json.JSONDecodeError as e:
            raise LLMError(f"Model did not return JSON: {text[:300]}") from e


class GeminiLLM:
    name = "gemini"

    def __init__(self, model: str | None = None):
        try:
            from google import genai
        except ImportError as e:
            raise LLMError("pip install 'arena-narrator[gemini]'") from e
        self.client = genai.Client()
        self.model = model or DEFAULT_MODELS[self.name]

    def complete_json(self, system: str, user: str, schema: dict) -> dict:
        resp = self.client.models.generate_content(
            model=self.model,
            contents=user,
            config={
                "system_instruction": system,
                "response_mime_type": "application/json",
                "response_json_schema": schema,
            },
        )
        try:
            return _loads(resp.text or "")
        except json.JSONDecodeError as e:
            raise LLMError(f"Model did not return JSON: {(resp.text or '')[:300]}") from e


class OpenRouterLLM:
    """Any model on openrouter.ai through its OpenAI-compatible API (OPENROUTER_API_KEY)."""

    name = "openrouter"
    URL = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(self, model: str | None = None):
        self.key = os.environ.get("OPENROUTER_API_KEY")
        if not self.key:
            raise LLMError("Set OPENROUTER_API_KEY to use --provider openrouter")
        self.model = model or DEFAULT_MODELS[self.name]

    def complete_json(self, system: str, user: str, schema: dict) -> dict:
        import httpx

        body = {
            "model": self.model,
            "max_tokens": 16000,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "narration", "strict": True, "schema": schema},
            },
        }
        headers = {
            "Authorization": f"Bearer {self.key}",
            "HTTP-Referer": "https://github.com/gamaerry/arena-narrator",
            "X-Title": "arena-narrator",
        }
        data = self._post(httpx, body, headers)
        if "error" in data and "response_format" in str(data["error"]):
            data = self._post(httpx, self._json_object_body(body, schema), headers)
        if "error" in data:
            raise LLMError(f"OpenRouter error: {data['error']}")
        if not data.get("choices"):
            raise LLMError(f"OpenRouter returned no choices: {str(data)[:300]}")
        choice = data["choices"][0]
        msg = choice.get("message") or {}
        if msg.get("refusal") or choice.get("finish_reason") in ("refusal", "content_filter"):
            raise LLMError(f"{self.model} refused the request: {msg.get('refusal') or ''}")
        text = msg.get("content") or ""
        try:
            return _loads(text)
        except json.JSONDecodeError as e:
            reason = choice.get("finish_reason")
            raise LLMError(f"{self.model} did not return JSON ({reason}): {text[:300]}") from e


    def _post(self, httpx, body: dict, headers: dict) -> dict:
        """POST with backoff on rate limits / transient upstream errors (common on :free)."""
        for attempt in range(6):
            r = httpx.post(self.URL, json=body, headers=headers, timeout=900)
            if r.status_code in (429, 502, 503) and attempt < 5:
                wait = int(r.headers.get("retry-after") or 0) or 10 * 2**attempt
                print(f"  OpenRouter {r.status_code}; retrying in {wait}s …", file=sys.stderr)
                time.sleep(min(wait, 120))
                continue
            if r.status_code == 400 and "response_format" in r.text:
                return {"error": r.text}
            if r.status_code != 200:
                raise LLMError(f"OpenRouter HTTP {r.status_code}: {r.text[:500]}")
            return r.json()
        raise LLMError("OpenRouter: too many retries")

    @staticmethod
    def _json_object_body(body: dict, schema: dict) -> dict:
        """Fallback for models without json_schema support: plain JSON mode + schema in prompt."""
        msgs = [dict(m) for m in body["messages"]]
        msgs[0]["content"] += (
            "\n\nReply with a single JSON object (no prose, no code fences) matching this "
            f"JSON Schema:\n{json.dumps(schema)}"
        )
        return {**body, "messages": msgs, "response_format": {"type": "json_object"}}


class ClaudeCLI:
    """Uses a local Claude Code install in headless mode (no API key needed)."""

    name = "claude-cli"

    def __init__(self, model: str | None = None):
        self.bin = shutil.which("claude")
        if not self.bin:
            raise LLMError("`claude` CLI not found on PATH")
        self.model = model or DEFAULT_MODELS[self.name]

    def complete_json(self, system: str, user: str, schema: dict) -> dict:
        cmd = [
            self.bin, "-p",
            "--model", self.model,
            "--output-format", "json",
            "--json-schema", json.dumps(schema),
            "--system-prompt", system,
            "--tools", "",
        ]
        proc = subprocess.run(cmd, input=user, capture_output=True, text=True, timeout=1800)
        try:
            envelope = json.loads(proc.stdout)
        except json.JSONDecodeError:
            msg = proc.stderr.strip() or proc.stdout[:500]
            raise LLMError(f"claude CLI failed: {msg}") from None
        if envelope.get("stop_reason") == "refusal":
            raise LLMError(
                "claude CLI: the request was flagged by safeguards (a false positive is possible "
                "on chess commentary). Try --provider anthropic or --provider gemini."
            )
        if envelope.get("is_error") or proc.returncode != 0:
            raise LLMError(f"claude CLI error: {str(envelope.get('result'))[:500]}")
        if isinstance(envelope.get("structured_output"), dict):
            return envelope["structured_output"]
        try:
            return _loads(envelope.get("result", ""))
        except (json.JSONDecodeError, TypeError) as e:
            result = str(envelope.get("result"))[:300]
            raise LLMError(f"claude CLI did not return JSON: {result}") from e


class TemplateLLM:
    """Offline fallback: no LLM at all. Every move gets a plain sentence (see narrate)."""

    name = "none"
    model = "template"

    def __init__(self, model: str | None = None):
        pass

    def complete_json(self, system: str, user: str, schema: dict) -> dict:
        return {"intro": "", "segments": [], "outro": "", "summary": ""}


PROVIDERS = {
    "anthropic": AnthropicLLM,
    "gemini": GeminiLLM,
    "openrouter": OpenRouterLLM,
    "claude-cli": ClaudeCLI,
    "none": TemplateLLM,
}


def get_llm(provider: str = "auto", model: str | None = None) -> LLM:
    if provider == "auto":
        if os.environ.get("ANTHROPIC_API_KEY"):
            provider = "anthropic"
        elif os.environ.get("OPENROUTER_API_KEY"):
            provider = "openrouter"
        elif os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
            provider = "gemini"
        elif shutil.which("claude"):
            provider = "claude-cli"
        else:
            raise LLMError(
                "No LLM available: set ANTHROPIC_API_KEY, OPENROUTER_API_KEY or GEMINI_API_KEY, "
                "install Claude Code "
                "(`claude`), or use --provider none for plain offline narration."
            )
    if provider not in PROVIDERS:
        raise LLMError(f"Unknown provider {provider!r}; choose from {', '.join(PROVIDERS)}")
    return PROVIDERS[provider](model)
