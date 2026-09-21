from __future__ import annotations
import json
from .base import TransportPrompt, TransportOut, BackendInfo

_SYSTEM_PROMPT = (
    "Output ONLY the requested JSON. You are a transporter: extract and structure "
    "information from the input. Never assert a fact. Never produce a numeric answer. "
    "Never add information not present in the input."
)

class OpenAIBackend:
    def __init__(self, url: str, model: str, api_key: str = "sk-placeholder",
                 context_length: int = 8192, **kwargs):
        self._url = url.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._context_length = context_length

    def transport(self, p: TransportPrompt) -> TransportOut:
        """I7: httpx POST to OpenAI-compatible /v1/chat/completions with JSON mode."""
        try:
            import httpx
        except ImportError:
            raise ImportError("httpx required: pip install httpx")
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": f"Task: {p.task}\nInput: {p.text}\nReturn JSON only."},
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": 512,
        }
        resp = httpx.post(
            f"{self._url}/v1/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=30,
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"]
        try:
            return TransportOut(json=json.loads(raw))
        except Exception:
            return TransportOut(json={"raw": raw})

    def info(self) -> BackendInfo:
        return BackendInfo(
            model_id=self._model,
            quantization=None,
            context_length=self._context_length,
            license_tag="openai-compatible",
        )
