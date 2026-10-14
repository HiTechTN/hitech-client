"""HCF adapter contract.

A backend = 1 file implementing AdapterInterface (~100 lines).
The frontend only speaks the normalized HCF API — never backend dialects.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator


@dataclass
class Capabilities:
    tools: bool = False       # agent tools (file edit, shell, ...)
    vision: bool = False      # image input parts
    audio_in: bool = False    # native audio understanding
    streaming: bool = True    # token streaming supported


@dataclass
class ModelInfo:
    id: str
    label: str = ""
    vision: bool = False

    def __post_init__(self):
        if not self.label:
            self.label = self.id


# Normalized content parts (frontend <-> core). Adapters translate.
#   {"type": "text", "text": "..."}
#   {"type": "image_url", "url": "data:image/jpeg;base64,..."}
#   {"type": "audio", "url": "data:audio/webm;base64,...", "format": "webm"}
#
# Normalized stream events (core -> frontend SSE):
#   {"type": "delta", "text": "..."}
#   {"type": "done", "full_text": "...", "usage": {...}}
#   {"type": "error", "message": "..."}


class AdapterInterface(ABC):
    """Every backend implements this. Keep it small on purpose."""

    id: str = "?"
    label: str = "?"

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities()

    @abstractmethod
    async def list_models(self) -> list[ModelInfo]:
        """Models exposed by this backend (fallback to defaults on error)."""

    @abstractmethod
    def chat_stream(self, *, model: str, messages: list[dict],
                    system: str | None = None,
                    temperature: float = 0.7) -> AsyncIterator[dict]:
        """Yield normalized events (delta/done/error). Must be an async generator."""

    async def abort(self, job_id: str) -> None:
        """Best-effort cancel. Default: no-op (stateless HTTP backends)."""

    async def health(self) -> bool:
        """True if the backend answers. Default: list_models works."""
        try:
            await self.list_models()
            return True
        except Exception:
            return False


class AdapterRegistry:
    """Holds backend instances. New backend = registry.register(MyAdapter())."""

    def __init__(self):
        self._adapters: dict[str, AdapterInterface] = {}

    def register(self, adapter: AdapterInterface) -> None:
        self._adapters[adapter.id] = adapter

    def get(self, backend_id: str) -> AdapterInterface:
        try:
            return self._adapters[backend_id]
        except KeyError:
            raise KeyError(f"unknown backend: {backend_id}")

    def ids(self) -> list[str]:
        return list(self._adapters.keys())

    async def describe(self) -> list[dict]:
        out = []
        for a in self._adapters.values():
            caps = a.capabilities
            out.append({
                "id": a.id, "label": a.label,
                "capabilities": {
                    "tools": caps.tools, "vision": caps.vision,
                    "audio_in": caps.audio_in, "streaming": caps.streaming,
                },
                "healthy": await a.health(),
            })
        return out
