"""AI provider abstraction for Gmail Auto-Cleanup.

To add a new provider:
1. Subclass BaseAIProvider and implement complete().
2. Add a branch in get_provider().
"""

import json
import os
from abc import ABC, abstractmethod


class BaseAIProvider(ABC):
    """Minimal interface every AI provider must implement."""

    @abstractmethod
    def complete(self, prompt: str) -> str:
        """Send prompt, return raw text response."""


class GeminiProvider(BaseAIProvider):
    """Google Gemini via the google-genai SDK."""

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    def complete(self, prompt: str) -> str:
        from google import genai
        print(f"Invoking Gemini provider ({self.model})...")
        client = genai.Client(api_key=self.api_key)
        try:
            response = client.models.generate_content(
                model=self.model,
                contents=prompt,
                config={"response_mime_type": "application/json"},
            )
        except Exception:
            response = client.models.generate_content(
                model=self.model,
                contents=prompt,
            )
        return response.text.strip()


class OpenAICompatProvider(BaseAIProvider):
    """Any OpenAI-compatible endpoint (OpenCode Go, Ollama, GPT-4o, …)."""

    def __init__(self, api_key: str, model: str, base_url: str, timeout: int = 60):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.timeout = timeout

    def complete(self, prompt: str) -> str:
        import urllib.request
        print(f"Invoking OpenAI-compat provider ({self.model}) at {self.base_url}...")

        endpoint = self.base_url.rstrip("/")
        if not endpoint.endswith("/chat/completions"):
            endpoint = f"{endpoint}/chat/completions"

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
        }
        req = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "Gmail-Cleanup/1.0",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as response:
            res_data = json.loads(response.read().decode("utf-8"))
        return res_data["choices"][0]["message"]["content"].strip()


def get_provider(ai_config: dict) -> BaseAIProvider | None:
    """Factory: read ai config dict, return a ready provider or None if no key."""
    provider_name = ai_config.get("provider", "gemini").lower()
    model = ai_config.get("model", "")
    base_url = ai_config.get("base_url", "")
    api_key_env = ai_config.get("api_key_env", "")

    # Resolve API key: explicit value in config takes priority, then env var
    api_key = ai_config.get("api_key") or os.environ.get(api_key_env) or ""

    if provider_name == "gemini":
        model = model or "gemini-2.5-flash"
        # Also try GEMINI_API_KEY as a fallback env var name
        if not api_key:
            api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            return None
        return GeminiProvider(api_key=api_key, model=model)

    # All OpenAI-compatible providers (opencoder-go, ollama, openai, etc.)
    model = model or "deepseek-chat"
    # Also try OPENCODE_API_KEY as a legacy fallback
    if not api_key:
        api_key = os.environ.get("OPENCODE_API_KEY", "")
    if not api_key:
        return None
    return OpenAICompatProvider(
        api_key=api_key,
        model=model,
        base_url=base_url or "https://opencode.ai/zen/go/v1",
    )
