"""HCF Core server — stable API for ALL frontends (web/desktop/mobile).

    GET  /api/hc/health
    GET  /api/hc/backends
    GET  /api/hc/models?backend=<id>
    GET  /api/hc/sessions            POST /api/hc/sessions
    GET  /api/hc/sessions/:id        PATCH /api/hc/sessions/:id
                                     DELETE /api/hc/sessions/:id
    GET  /api/hc/sessions/:id/messages
    POST /api/hc/sessions/:id/messages   (SSE stream, or ?stream=false for JSON)

Message POST body: {"content": "text..." | [{type,text|image_url,...}],
                    "backend": "ollama", "model": "...", "system": "...",
                    "temperature": 0.7}
SSE events: {"type":"delta","text"} ... {"type":"done","full_text"}
"""
import json
import os
import secrets
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .adapters.base import AdapterRegistry
from .adapters.openai_compat import OpenAICompatAdapter
from .config import get_config
from .store import Store

cfg = get_config()
Path(cfg.server.data_dir).mkdir(parents=True, exist_ok=True)
store = Store(cfg.server.data_dir)

registry = AdapterRegistry()
registry.register(OpenAICompatAdapter(
    id="ollama", label="Ollama (local)",
    base_url=cfg.ollama.base_url, default_model=cfg.ollama.model,
    vision_model=cfg.ollama.vision_model))
if cfg.openrouter.api_key:
    registry.register(OpenAICompatAdapter(
        id="openrouter", label="OpenRouter (cloud)",
        base_url=cfg.openrouter.base_url, api_key=cfg.openrouter.api_key,
        default_model=cfg.openrouter.model))

app = FastAPI(title="HiTech Client Framework")
if cfg.server.cors_origins:
    app.add_middleware(
        CORSMiddleware, allow_origins=cfg.server.cors_origins,
        allow_methods=["*"], allow_headers=["*"])


def _as_parts(content) -> list[dict]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return [p for p in content if isinstance(p, dict) and p.get("type")]
    raise HTTPException(status_code=400, detail="content must be text or parts[]")


class SessionIn(BaseModel):
    title: str = "Conversation"
    backend: str = ""
    model: str = ""


class SessionPatch(BaseModel):
    title: str | None = None
    backend: str | None = None
    model: str | None = None


class MessageIn(BaseModel):
    content: object
    backend: str = ""
    model: str = ""
    system: str | None = None
    temperature: float = 0.7


@app.get("/api/hc/health")
async def health():
    return {"ok": True, "service": "hitech-client", "backends": await registry.describe()}


@app.get("/api/hc/backends")
async def backends():
    return {"backends": await registry.describe()}


@app.get("/api/hc/models")
async def models(backend: str = ""):
    bid = backend or cfg.server.default_backend
    try:
        adapter = registry.get(bid)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown backend: {bid}")
    return {"backend": bid,
            "models": [{"id": m.id, "label": m.label, "vision": m.vision}
                       for m in await adapter.list_models()]}


@app.get("/api/hc/sessions")
async def list_sessions():
    return {"sessions": store.list_sessions()}


@app.post("/api/hc/sessions")
async def create_session(body: SessionIn):
    bid = body.backend or cfg.server.default_backend
    return store.create_session(title=body.title or "Conversation",
                                backend=bid, model=body.model)


@app.get("/api/hc/sessions/{sid}")
async def get_session(sid: str):
    s = store.get_session(sid)
    if not s:
        raise HTTPException(status_code=404, detail="session introuvable")
    return s


@app.patch("/api/hc/sessions/{sid}")
async def patch_session(sid: str, body: SessionPatch):
    s = store.update_session(sid, **{k: v for k, v in body.model_dump().items()
                                     if v is not None})
    if not s:
        raise HTTPException(status_code=404, detail="session introuvable")
    return s


@app.delete("/api/hc/sessions/{sid}")
async def delete_session(sid: str):
    if not store.delete_session(sid):
        raise HTTPException(status_code=404, detail="session introuvable")
    return {"ok": True}


@app.get("/api/hc/sessions/{sid}/messages")
async def get_messages(sid: str):
    if not store.get_session(sid):
        raise HTTPException(status_code=404, detail="session introuvable")
    return {"messages": store.list_messages(sid)}


@app.post("/api/hc/sessions/{sid}/messages")
async def post_message(sid: str, body: MessageIn, request: Request, stream: bool = True):
    s = store.get_session(sid)
    if not s:
        raise HTTPException(status_code=404, detail="session introuvable")
    parts = _as_parts(body.content)
    if not any(p.get("type") == "text" and (p.get("text") or "").strip()
               or p.get("type") != "text" for p in parts):
        raise HTTPException(status_code=400, detail="message vide")
    bid = body.backend or s.get("backend") or cfg.server.default_backend
    try:
        adapter = registry.get(bid)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown backend: {bid}")
    model = body.model or s.get("model") or ""
    store.add_message(sid, "user", parts)
    history = [{"role": m["role"], "content": m["content"]}
               for m in store.list_messages(sid)]
    if bid != (s.get("backend") or "") or (model and model != (s.get("model") or "")):
        store.update_session(sid, backend=bid, model=model)

    async def event_gen():
        full: list[str] = []
        try:
            async for ev in adapter.chat_stream(
                    model=model, messages=history, system=body.system,
                    temperature=body.temperature):
                if ev.get("type") == "delta" and ev.get("text"):
                    full.append(ev["text"])
                if ev.get("type") == "done" and not full and ev.get("full_text"):
                    full.append(ev["full_text"])
                yield f"data: {json.dumps(ev)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)[:300]})}\n\n"
            full.append(f"\n[erreur: {e}]")
        text = "".join(full)
        if text.strip():
            store.add_message(sid, "assistant", [{"type": "text", "text": text}])

    if not stream:
        chunks: list[str] = []
        err = ""
        async for ev in adapter.chat_stream(
                model=model, messages=history, system=body.system,
                temperature=body.temperature):
            if ev.get("type") == "delta":
                chunks.append(ev.get("text", ""))
            elif ev.get("type") == "error":
                err = ev.get("message", "error")
        text = "".join(chunks)
        if err and not text:
            raise HTTPException(status_code=502, detail=err)
        store.add_message(sid, "assistant", [{"type": "text", "text": text}])
        return {"reply": text, "error": err}
    return StreamingResponse(event_gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


# ---- token gate (mandatory once exposed on LAN / public tunnel) -----------
# Set HCF_PUBLIC_TOKEN env -> every route except /login requires it
# (cookie hcf_token, header `Authorization: Bearer`, or `?token=`).
def _want_token() -> str:
    return os.getenv("HCF_PUBLIC_TOKEN", "")


LOGIN_HTML = """<!DOCTYPE html><html lang="fr"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>HiTech Client — Accès</title></head>
<body style="font-family:system-ui,sans-serif;background:#0b1220;color:#e8f0fc;height:100vh;display:flex;align-items:center;justify-content:center;margin:0;">
<form method="post" action="/login" style="background:#111c30;border:1px solid #24344f;border-radius:12px;padding:2rem;width:min(360px,92vw);">
<h3 style="margin-top:0;color:#38bdf8;">🔐 HiTech Client</h3>
<p style="color:#8ba0bd;font-size:.85rem;">Accès protégé — entre le token.</p>
<input type="password" name="token" required autofocus placeholder="token"
 style="width:100%;box-sizing:border-box;padding:.6rem;border-radius:8px;border:1px solid #24344f;background:#0b1220;color:#fff;margin-bottom:.8rem;">
<button type="submit" style="width:100%;background:#0284c7;color:#fff;border:none;padding:.6rem;border-radius:8px;font-weight:bold;cursor:pointer;">Entrer</button>
</form></body></html>"""


@app.get("/login", response_class=HTMLResponse)
async def login_page():
    if not _want_token():
        return RedirectResponse("/", status_code=303)
    return LOGIN_HTML


@app.post("/login")
async def login(token: str = Form("")):
    want = _want_token()
    if want and token and secrets.compare_digest(token, want):
        res = RedirectResponse("/", status_code=303)
        res.set_cookie("hcf_token", token, httponly=True, samesite="lax",
                       max_age=30 * 24 * 3600)
        return res
    raise HTTPException(status_code=401, detail="token invalide")


@app.middleware("http")
async def token_gate(request: Request, call_next):
    if not _want_token():
        return await call_next(request)
    path = request.url.path
    if path == "/login":
        return await call_next(request)
    tok = request.cookies.get("hcf_token", "")
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        tok = auth[7:].strip() or tok
    if not tok:
        tok = request.query_params.get("token", "")
    if tok and secrets.compare_digest(tok, _want_token()):
        return await call_next(request)
    if path.startswith("/api/"):
        return JSONResponse({"detail": "auth requise"}, status_code=401)
    return RedirectResponse("/login", status_code=303)


# ---- serve the web UI (same process; desktop/mobile wrap the same files) ---
WEB_DIR = Path(__file__).resolve().parent.parent.parent / "apps" / "web"
if WEB_DIR.exists():
    @app.get("/", response_class=HTMLResponse)
    async def index():
        return (WEB_DIR / "index.html").read_text(encoding="utf-8")

    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="web")
