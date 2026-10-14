"""OpenCode adapter — full agent backend (tools, file edit, shell).

Talks to `opencode serve` (OpenAPI, verified empirically on v1.4.9):
  POST /session -> {id} · POST /session/:id/message {model, parts, system}
  -> blocking {info, parts[]} (text parts carry the answer).
One OpenCode session per HCF session (persisted link in HCF store).

Model format: "providerID/modelID" (e.g. "ollama-local/qwen2.5-coder:7b").
v1: text in/out (image parts skipped — native OC vision later).
"""
import json
from typing import AsyncIterator

import httpx

from .base import AdapterInterface, Capabilities, ModelInfo

VISION_HINTS = ("vision", "-vl", "llava", "gpt-4o", "claude-3", "claude-4",
                "gemini", "qwen-vl", "moondream")


class OpenCodeAdapter(AdapterInterface):
    id = "opencode"
    label = "OpenCode (agent)"

    def __init__(self, base_url: str, store,
                 default_provider: str = "ollama-local",
                 default_model: str = "qwen2.5:7b-instruct",
                 timeout: float = 300.0):
        self.base_url = base_url.rstrip("/")
        self.store = store
        self.default_provider = default_provider
        self.default_model = default_model
        self.timeout = timeout

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(tools=True, vision=False, audio_in=False, streaming=False)

    @staticmethod
    def _vision(model_id: str) -> bool:
        return any(h in model_id.lower() for h in VISION_HINTS)

    def _split_model(self, model: str) -> tuple[str, str]:
        if "/" in (model or ""):
            provider, mid = model.split("/", 1)
            if provider and mid:
                return provider, mid
        return self.default_provider, self.default_model

    async def list_models(self) -> list[ModelInfo]:
        try:
            async with httpx.AsyncClient(timeout=15) as cli:
                r = await cli.get(f"{self.base_url}/provider")
                r.raise_for_status()
                providers = (r.json().get("all") or [])
        except Exception:
            providers = []
        out = []
        for p in providers:
            pid = p.get("id", "")
            for m in (p.get("models") or {}).keys():
                out.append(ModelInfo(id=f"{pid}/{m}", label=f"{m} ({pid})",
                                     vision=self._vision(m)))
        if not out:
            out = [ModelInfo(id=f"{self.default_provider}/{self.default_model}")]
        # preferred default first
        preferred = f"{self.default_provider}/{self.default_model}"
        out.sort(key=lambda m: 0 if m.id == preferred else 1)
        return out

    async def _oc_session(self, hcf_sid: str, title: str = "HCF") -> str:
        oc_id = self.store.get_link(hcf_sid)
        if oc_id:
            return oc_id
        async with httpx.AsyncClient(timeout=15) as cli:
            r = await cli.post(f"{self.base_url}/session", json={"title": title[:80]})
            r.raise_for_status()
            oc_id = r.json()["id"]
        self.store.set_link(hcf_sid, oc_id)
        return oc_id

    @staticmethod
    def _to_parts(messages: list[dict]) -> list[dict]:
        """Last user message only (OC keeps its own history per session)."""
        for m in reversed(messages):
            if m.get("role") != "user":
                continue
            texts = [p.get("text", "") for p in (m.get("content") or [])
                     if isinstance(p, dict) and p.get("type") == "text"
                     and (p.get("text") or "").strip()]
            if texts:
                return [{"type": "text", "text": "\n".join(texts)}]
        return [{"type": "text", "text": "(message vide)"}]

    async def chat_stream(self, *, model: str, messages: list[dict],
                          system: str | None = None,
                          temperature: float = 0.7,
                          session_key: str = "") -> AsyncIterator[dict]:
        provider, mid = self._split_model(model)
        try:
            oc_id = await self._oc_session(session_key or "default")
        except Exception as e:
            yield {"type": "error", "message": f"session opencode: {e}"[:300]}
            return
        payload: dict = {"model": {"providerID": provider, "modelID": mid},
                         "parts": self._to_parts(messages)}
        if system:
            payload["system"] = system
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as cli:
                r = await cli.post(f"{self.base_url}/session/{oc_id}/message",
                                   json=payload)
                if r.status_code >= 400:
                    yield {"type": "error",
                           "message": f"opencode {r.status_code}: {r.text[:200]}"}
                    return
                data = r.json()
        except httpx.TimeoutException:
            yield {"type": "error", "message": "opencode: délai dépassé (timeout)"}
            return
        except Exception as e:
            yield {"type": "error", "message": f"opencode: {e}"[:300]}
            return
        texts = [p.get("text", "") for p in (data.get("parts") or [])
                 if p.get("type") == "text" and p.get("text")]
        full = "".join(texts).strip()
        if not full:
            finish = (data.get("info") or {}).get("finish", "?")
            yield {"type": "error",
                   "message": f"l'agent n'a rien produit (finish={finish})"}
            return
        yield {"type": "delta", "text": full}
        yield {"type": "done", "full_text": full, "usage": {}}

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5) as cli:
                r = await cli.get(f"{self.base_url}/global/health")
                return r.status_code == 200 and r.json().get("healthy") is True
        except Exception:
            return False
