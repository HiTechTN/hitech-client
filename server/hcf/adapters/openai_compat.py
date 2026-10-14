"""OpenAI-compatible adapter — ONE implementation, dozens of providers.

Covers: Ollama (/v1), OpenRouter, LM Studio, vLLM, Mistral, DeepSeek, xAI...
Speaks POST {base}/chat/completions with SSE streaming, yields normalized
HCF events (delta/done/error). Multimodal parts pass through natively.
"""
import json
from typing import AsyncIterator

import httpx

from .base import AdapterInterface, Capabilities, ModelInfo

VISION_HINTS = ("vision", "-vl", "llava", "gpt-4o", "claude-3", "claude-4",
                "gemini", "qwen-vl", "minicpm", "moondream")


class OpenAICompatAdapter(AdapterInterface):
    def __init__(self, *, id: str, label: str, base_url: str,
                 api_key: str = "", default_model: str = "",
                 vision_model: str = "", timeout: float = 120.0):
        self.id = id
        self.label = label
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.default_model = default_model
        self.vision_model = vision_model
        self.timeout = timeout

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(tools=False, vision=True, audio_in=False, streaming=True)

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    @staticmethod
    def _looks_vision(model_id: str) -> bool:
        m = model_id.lower()
        return any(h in m for h in VISION_HINTS)

    async def list_models(self) -> list[ModelInfo]:
        try:
            async with httpx.AsyncClient(timeout=10) as cli:
                r = await cli.get(f"{self.base_url}/models", headers=self._headers())
                r.raise_for_status()
                ids = [m.get("id", "") for m in r.json().get("data", []) if m.get("id")]
        except Exception:
            ids = []
        if not ids:
            ids = [m for m in (self.default_model, self.vision_model) if m]
        if self.default_model and self.default_model not in ids:
            ids.insert(0, self.default_model)
        return [ModelInfo(id=i, vision=(i == self.vision_model or self._looks_vision(i)))
                for i in ids]

    @staticmethod
    def _to_openai(messages: list[dict], system: str | None) -> list[dict]:
        out = []
        if system:
            out.append({"role": "system", "content": system})
        for m in messages:
            role = m.get("role", "user")
            parts = m.get("content", [])
            if isinstance(parts, str):
                out.append({"role": role, "content": parts})
                continue
            chunks = []
            for p in parts:
                t = p.get("type")
                if t == "text":
                    chunks.append({"type": "text", "text": p.get("text", "")})
                elif t == "image_url" and p.get("url"):
                    chunks.append({"type": "image_url",
                                   "image_url": {"url": p["url"]}})
                # audio parts are transcribed upstream; skip raw audio here
            if len(chunks) == 1 and chunks[0]["type"] == "text":
                out.append({"role": role, "content": chunks[0]["text"]})
            elif chunks:
                out.append({"role": role, "content": chunks})
        return out

    async def chat_stream(self, *, model: str, messages: list[dict],
                          system: str | None = None,
                          temperature: float = 0.7,
                          session_key: str = "") -> AsyncIterator[dict]:
        _ = session_key  # stateless backend: history comes in messages[]
        payload = {"model": model or self.default_model,
                   "messages": self._to_openai(messages, system),
                   "temperature": temperature, "stream": True}
        full: list[str] = []
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as cli:
                async with cli.stream("POST", f"{self.base_url}/chat/completions",
                                      headers=self._headers(), json=payload) as r:
                    if r.status_code >= 400:
                        body = (await r.aread()).decode()[:300]
                        yield {"type": "error",
                               "message": f"provider {r.status_code}: {body}"}
                        return
                    async for line in r.aiter_lines():
                        line = line.strip()
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            obj = json.loads(data)
                        except ValueError:
                            continue
                        delta = (((obj.get("choices") or [{}])[0].get("delta") or {})
                                 .get("content"))
                        if delta:
                            full.append(delta)
                            yield {"type": "delta", "text": delta}
                        err = obj.get("error")
                        if err:
                            yield {"type": "error",
                                   "message": str(err.get("message", err))[:300]}
                            return
        except httpx.TimeoutException:
            yield {"type": "error", "message": "provider timeout"}
            return
        except Exception as e:
            yield {"type": "error", "message": f"provider error: {e}"[:300]}
            return
        yield {"type": "done", "full_text": "".join(full), "usage": {}}

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5) as cli:
                r = await cli.get(f"{self.base_url}/models", headers=self._headers())
                return r.status_code < 500
        except Exception:
            return False
