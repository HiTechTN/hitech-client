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

from fastapi import FastAPI, Form, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import auth
from .adapters.base import AdapterRegistry
from .adapters.opencode import OpenCodeAdapter
from .adapters.openai_compat import OpenAICompatAdapter
from .config import get_config
from .media import video as media_video
from .media import voice as media_voice
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
        default_model=cfg.openrouter.model, free_only=True))
if cfg.opencode.enabled:
    registry.register(OpenCodeAdapter(
        base_url=cfg.opencode.base_url, store=store,
        default_provider=cfg.opencode.provider,
        default_model=cfg.opencode.model))

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
    regen: bool = False  # regenerate: drop trailing assistant reply, re-answer


class EmailIn(BaseModel):
    email: str


class VerifyIn(BaseModel):
    email: str
    code: str


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


# ---- user auth (email + PIN) --------------------------------------------
@app.post("/api/hc/auth/request-code")
async def auth_request_code(body: EmailIn):
    try:
        return auth.request_code(store, body.email)
    except ValueError as e:
        raise HTTPException(status_code=429 if "attendez" in str(e) or "trop" in str(e) else 400,
                            detail=str(e))


@app.post("/api/hc/auth/verify")
async def auth_verify(body: VerifyIn, response: Response):
    try:
        r = auth.verify_code(store, body.email, body.code)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    res = JSONResponse({"user": r["user"], "token": r["token"]})
    res.set_cookie("hcf_user", r["token"], httponly=True, samesite="none",
                   secure=True, max_age=30 * 24 * 3600)
    return res


@app.get("/api/hc/me")
async def me(request: Request):
    u = getattr(request.state, "user", None)
    if not u:
        raise HTTPException(status_code=401, detail="non connecté")
    return {"user": u}


@app.post("/api/hc/auth/logout")
async def auth_logout(response: Response):
    res = JSONResponse({"ok": True})
    res.delete_cookie("hcf_user")
    return res


# ---- OAuth (Google / GitHub) ---------------------------------------------
@app.get("/api/hc/auth/oauth/{provider}/start")
async def oauth_start(provider: str):
    if not auth.oauth_provider_ok(provider):
        raise HTTPException(status_code=404, detail=f"oauth {provider}: non configuré")
    state = secrets.token_urlsafe(32)
    res = RedirectResponse(auth.oauth_authorize_url(provider, state), status_code=303)
    res.set_cookie("oauth_state", state, httponly=True, samesite="lax",
                   max_age=600, path=f"/api/hc/auth/oauth/{provider}")
    return res


@app.get("/api/hc/auth/oauth/{provider}/callback")
async def oauth_callback(provider: str, request: Request):
    if not auth.oauth_provider_ok(provider):
        raise HTTPException(status_code=404, detail=f"oauth {provider}: non configuré")
    want = request.cookies.get("oauth_state", "")
    got = request.query_params.get("state", "")
    if not want or not got or not secrets.compare_digest(want, got):
        raise HTTPException(status_code=400, detail="oauth: state invalide (CSRF)")
    code = request.query_params.get("code", "")
    if not code:
        raise HTTPException(status_code=400, detail="oauth: code manquant")
    try:
        profile = await auth.oauth_exchange(provider, code)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    user = store.get_or_create_user(profile["email"])
    store.touch_login(user["id"])
    if profile["name"] and not user.get("name"):
        with store._lock:
            store._conn.execute("UPDATE users SET name=? WHERE id=?",
                                (profile["name"][:80], user["id"]))
            store._conn.commit()
        user["name"] = profile["name"]
    token = auth.make_user_token(user["id"], user["email"])
    res = RedirectResponse("/", status_code=303)
    res.set_cookie("hcf_user", token, httponly=True, samesite="none",
                   secure=True, max_age=30 * 24 * 3600)
    res.delete_cookie("oauth_state", path=f"/api/hc/auth/oauth/{provider}")
    return res


def _scope_uid(request: Request) -> str | None:
    """user_id filter for session routes; None = admin (sees everything)."""
    if getattr(request.state, "auth_kind", "") == "user":
        return request.state.user["uid"]
    return None


def _own_session(request: Request, sid: str) -> dict:
    s = store.get_session(sid)
    if not s:
        raise HTTPException(status_code=404, detail="session introuvable")
    uid = _scope_uid(request)
    if uid is not None and s.get("user_id", "") != uid:
        raise HTTPException(status_code=404, detail="session introuvable")
    return s


@app.get("/api/hc/sessions")
async def list_sessions(request: Request):
    return {"sessions": store.list_sessions(user_id=_scope_uid(request))}


@app.post("/api/hc/sessions")
async def create_session(request: Request, body: SessionIn):
    bid = body.backend or cfg.server.default_backend
    return store.create_session(title=body.title or "Conversation",
                                backend=bid, model=body.model,
                                user_id=_scope_uid(request) or "")


@app.get("/api/hc/sessions/{sid}")
async def get_session(request: Request, sid: str):
    return _own_session(request, sid)


@app.patch("/api/hc/sessions/{sid}")
async def patch_session(request: Request, sid: str, body: SessionPatch):
    _own_session(request, sid)
    s = store.update_session(sid, **{k: v for k, v in body.model_dump().items()
                                     if v is not None})
    if not s:
        raise HTTPException(status_code=404, detail="session introuvable")
    return s


@app.delete("/api/hc/sessions/{sid}")
async def delete_session(request: Request, sid: str):
    _own_session(request, sid)
    if not store.delete_session(sid):
        raise HTTPException(status_code=404, detail="session introuvable")
    return {"ok": True}


@app.get("/api/hc/sessions/{sid}/messages")
async def get_messages(request: Request, sid: str):
    _own_session(request, sid)
    return {"messages": store.list_messages(sid)}


@app.post("/api/hc/sessions/{sid}/messages")
async def post_message(sid: str, body: MessageIn, request: Request, stream: bool = True):
    s = _own_session(request, sid)
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
    if body.regen:
        store.delete_last_assistant(sid)
    else:
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
                    temperature=body.temperature, session_key=sid):
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
                temperature=body.temperature, session_key=sid):
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
    # serve the SPA: its overlay handles email+PIN login (and admin token)
    idx = WEB_DIR / "index.html"
    if idx.exists():
        return HTMLResponse(idx.read_text(encoding="utf-8"))
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
    if path == "/login" or path.startswith("/hc-static/"):
        return await call_next(request)
    tok = request.cookies.get("hcf_token", "") or request.cookies.get("hcf_user", "")
    auth_kind, user = "admin", None
    authz = request.headers.get("authorization", "")
    if authz.lower().startswith("bearer "):
        tok = authz[7:].strip() or tok
    # user token (email login) takes precedence when it parses
    ut = None
    if tok and "." in tok:
        ut = auth.parse_user_token(tok)
    if ut:
        auth_kind, user = "user", ut
        urow = store.get_user(ut["uid"])
        if urow:
            user = {**ut, "name": urow["name"]}
    elif tok and secrets.compare_digest(tok, _want_token()):
        pass  # admin via public token
    else:
        tok = request.query_params.get("token", "")
        if tok and "." in tok:
            ut = auth.parse_user_token(tok)
            if ut:
                auth_kind, user = "user", ut
                urow = store.get_user(ut["uid"])
                if urow:
                    user = {**ut, "name": urow["name"]}
            tok = "" if ut else tok
        if not ut and not (tok and secrets.compare_digest(tok, _want_token())):
            # self-service auth endpoints open once SMTP is configured
            if path.startswith("/api/hc/auth/") and (auth.AUTH_OPEN or auth.OAUTH_ENABLED):
                request.state.auth_kind = "anon"
                request.state.user = None
                return await call_next(request)
            if path.startswith("/api/"):
                return JSONResponse({"detail": "auth requise"}, status_code=401)
            return RedirectResponse("/login", status_code=303)
    request.state.auth_kind = auth_kind
    request.state.user = user
    return await call_next(request)


app.include_router(media_video.router)
app.include_router(media_voice.router)


# ---- serve the web UI (same process; desktop/mobile wrap the same files) ---
WEB_DIR = Path(__file__).resolve().parent.parent.parent / "apps" / "web"
if WEB_DIR.exists():
    @app.get("/", response_class=HTMLResponse)
    async def index():
        return (WEB_DIR / "index.html").read_text(encoding="utf-8")

    # /hc-static (NOT /static): avoids collision with the Drive's /static/*
    # when both are served behind lab.hitech.tn via the edge worker.
    app.mount("/hc-static", StaticFiles(directory=str(WEB_DIR)), name="web")
