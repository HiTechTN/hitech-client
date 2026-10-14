"""HCF configuration — everything via environment, sane local defaults."""
import os
from dataclasses import dataclass, field
from pathlib import Path


def _root() -> Path:
    return Path(__file__).resolve().parent.parent.parent  # server/


@dataclass
class OllamaCfg:
    base_url: str = "http://localhost:11434/v1"
    model: str = "qwen2.5:7b-instruct-q4_K_M"
    vision_model: str = "qwen2.5vl:7b"


@dataclass
class OpenRouterCfg:
    base_url: str = "https://openrouter.ai/api/v1"
    api_key: str = ""
    model: str = "meta-llama/llama-3.1-8b-instruct:free"


@dataclass
class OpenCodeCfg:
    base_url: str = "http://127.0.0.1:4097"
    enabled: bool = True
    provider: str = "ollama-local"
    model: str = "qwen2.5:7b-instruct"


@dataclass
class ServerCfg:
    host: str = "127.0.0.1"
    port: int = 8096
    data_dir: str = ""
    default_backend: str = "ollama"
    default_model: str = ""
    cors_origins: list = field(default_factory=list)


@dataclass
class HCFConfig:
    server: ServerCfg
    ollama: OllamaCfg
    openrouter: OpenRouterCfg
    opencode: OpenCodeCfg

    @classmethod
    def from_env(cls) -> "HCFConfig":
        root = _root()
        data_dir = os.getenv("HCF_DATA_DIR", str(root / "data"))
        cors = [o.strip() for o in os.getenv("HCF_CORS", "").split(",") if o.strip()]
        return cls(
            server=ServerCfg(
                host=os.getenv("HCF_HOST", "127.0.0.1"),
                port=int(os.getenv("HCF_PORT", "8096")),
                data_dir=data_dir,
                default_backend=os.getenv("HCF_DEFAULT_BACKEND", "ollama"),
                default_model=os.getenv("HCF_DEFAULT_MODEL", ""),
                cors_origins=cors,
            ),
            ollama=OllamaCfg(
                base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
                model=os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct-q4_K_M"),
                vision_model=os.getenv("OLLAMA_VISION_MODEL", "qwen2.5vl:7b"),
            ),
            openrouter=OpenRouterCfg(
                base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
                api_key=os.getenv("OPENROUTER_API_KEY", ""),
                model=os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.1-8b-instruct:free"),
            ),
            opencode=OpenCodeCfg(
                base_url=os.getenv("OC_BASE_URL", "http://127.0.0.1:4097"),
                enabled=os.getenv("OC_ENABLED", "true").lower() not in ("0", "false", "no"),
                provider=os.getenv("OC_PROVIDER", "ollama-local"),
                model=os.getenv("OC_MODEL", "qwen2.5:7b-instruct"),
            ),
        )


_config = None


def get_config() -> HCFConfig:
    global _config
    if _config is None:
        _config = HCFConfig.from_env()
    return _config
