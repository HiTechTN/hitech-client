"""HCF user auth — email + 6-digit PIN, signed user tokens.

Flow: POST /api/hc/auth/request-code {email} -> PIN sent by email
      POST /api/hc/auth/verify {email, code}  -> user + signed token (cookie)

Delivery: SMTP if configured (SMTP_HOST/PORT/USER/PASS env), else the mail
is written to <data>/outbox/ for manual pickup. While SMTP is not configured
the auth endpoints stay behind the public token gate (admin-only testing).
HCF_AUTH_DEV_MODE=1 additionally returns the code inline (TEST ONLY).
"""
import hashlib
import hmac
import base64
import json
import os
import re
import secrets
import smtplib
import time
import uuid
from email.message import EmailMessage
from pathlib import Path

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
CODE_TTL = 600          # 10 min
RESEND_COOLDOWN = 60    # 60s between codes
MAX_PER_HOUR = 3
MAX_ATTEMPTS = 5
TOKEN_TTL = 30 * 24 * 3600

_SECRET = os.getenv("HCF_AUTH_SECRET", "") or os.getenv("HCF_PUBLIC_TOKEN", "")
DEV_MODE = os.getenv("HCF_AUTH_DEV_MODE", "0") == "1"
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USER or "hcf@hitech.tn")
AUTH_OPEN = bool(SMTP_HOST) or DEV_MODE  # self-service once mail works (or explicit test mode)

# ---- OAuth (Google / GitHub) — enabled once client id/secret are set ------
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET", "")
OAUTH_BASE = os.getenv("HCF_OAUTH_BASE", "https://client.hitech.tn")
OAUTH_ENABLED = bool((GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET) or
                     (GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET))


def oauth_provider_ok(provider: str) -> bool:
    return provider in ("google", "github") and {
        "google": GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET,
        "github": GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET,
    }.get(provider)


def oauth_redirect_uri(provider: str) -> str:
    return f"{OAUTH_BASE}/api/hc/auth/oauth/{provider}/callback"


def oauth_authorize_url(provider: str, state: str) -> str:
    import urllib.parse as up
    ru = oauth_redirect_uri(provider)
    if provider == "google":
        q = up.urlencode({"client_id": GOOGLE_CLIENT_ID, "redirect_uri": ru,
                          "response_type": "code", "scope": "openid email profile",
                          "state": state, "prompt": "select_account"})
        return f"https://accounts.google.com/o/oauth2/v2/auth?{q}"
    q = up.urlencode({"client_id": GITHUB_CLIENT_ID, "redirect_uri": ru,
                      "response_type": "code", "scope": "read:user user:email",
                      "state": state})
    return f"https://github.com/login/oauth/authorize?{q}"


async def oauth_exchange(provider: str, code: str) -> dict:
    """Code -> verified email + name. Raises ValueError on any failure."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=15) as cli:
            if provider == "google":
                r = await cli.post("https://oauth2.googleapis.com/token", data={
                    "code": code,
                    "client_id": GOOGLE_CLIENT_ID,
                    "client_secret": GOOGLE_CLIENT_SECRET,
                    "redirect_uri": oauth_redirect_uri(provider),
                    "grant_type": "authorization_code"})
                r.raise_for_status()
                at = r.json().get("access_token", "")
                r2 = await cli.get("https://openidconnect.googleapis.com/v1/userinfo",
                                   headers={"Authorization": f"Bearer {at}"})
                r2.raise_for_status()
                p = r2.json()
                if not p.get("email_verified"):
                    raise ValueError("email google non vérifié")
                return {"email": p["email"], "name": p.get("name", "")}
            # github
            r = await cli.post("https://github.com/login/oauth/access_token",
                               data={"code": code,
                                     "client_id": GITHUB_CLIENT_ID,
                                     "client_secret": GITHUB_CLIENT_SECRET,
                                     "redirect_uri": oauth_redirect_uri(provider)},
                               headers={"Accept": "application/json"})
            r.raise_for_status()
            at = r.json().get("access_token", "")
            if not at:
                raise ValueError("github: pas de token")
            h = {"Authorization": f"Bearer {at}", "Accept": "application/vnd.github+json"}
            r2 = await cli.get("https://api.github.com/user", headers=h)
            r2.raise_for_status()
            name = r2.json().get("name") or r2.json().get("login", "")
            r3 = await cli.get("https://api.github.com/user/emails", headers=h)
            r3.raise_for_status()
            primary = next((e for e in r3.json()
                            if e.get("primary") and e.get("verified")), None)
            if not primary:
                raise ValueError("github: email primaire non vérifié")
            return {"email": primary["email"], "name": name}
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"oauth {provider}: {e}")


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _b64u_d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_user_token(uid: str, email: str) -> str:
    payload = _b64u(json.dumps({"uid": uid, "email": email,
                                "exp": int(time.time()) + TOKEN_TTL}).encode())
    sig = _b64u(hmac.new(_SECRET.encode(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def parse_user_token(tok: str) -> dict | None:
    try:
        payload, sig = tok.split(".", 1)
        want = _b64u(hmac.new(_SECRET.encode(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, want):
            return None
        d = json.loads(_b64u_d(payload))
        if d.get("exp", 0) < time.time():
            return None
        return d
    except Exception:
        return None


def _hash_code(email: str, code: str) -> str:
    return hashlib.sha256(f"{email.lower()}:{code}:{_SECRET}".encode()).hexdigest()


def send_email(to: str, subject: str, body: str) -> str:
    """Returns delivery mode: 'smtp' or 'outbox'."""
    msg = EmailMessage()
    msg["From"] = SMTP_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    if SMTP_HOST:
        if SMTP_PORT == 465:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=15) as s:
                if SMTP_USER:
                    s.login(SMTP_USER, SMTP_PASS)
                s.send_message(msg)
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as s:
                s.starttls()
                if SMTP_USER:
                    s.login(SMTP_USER, SMTP_PASS)
                s.send_message(msg)
        return "smtp"
    outbox = Path(os.getenv("HCF_DATA_DIR", "/data/hitech-client/data")) / "outbox"
    outbox.mkdir(parents=True, exist_ok=True)
    f = outbox / f"{int(time.time())}_{to.replace('@', '_at_')}.txt"
    f.write_text(f"From: {SMTP_FROM}\nTo: {to}\nSubject: {subject}\n\n{body}\n")
    return "outbox"


def request_code(store, email: str) -> dict:
    email = (email or "").strip().lower()
    if not EMAIL_RE.match(email):
        raise ValueError("email invalide")
    row = store.get_login_code(email)
    now = int(time.time())
    if row:
        if now - row["sent"] < RESEND_COOLDOWN:
            raise ValueError(f"attendez {RESEND_COOLDOWN - (now - row['sent'])}s avant un nouveau code")
        if now - row["hour_start"] < 3600 and row["count_hour"] >= MAX_PER_HOUR:
            raise ValueError("trop de codes demandés — réessayez dans une heure")
    code = f"{secrets.randbelow(1000000):06d}"
    store.save_login_code(email, _hash_code(email, code), now + CODE_TTL, now)
    mode = send_email(
        email,
        "HiTech Client — votre code de connexion",
        f"Salam,\n\nVotre code de connexion HiTech Client :\n\n  {code}\n\n"
        f"Valable 10 minutes. Si vous n'avez pas demandé ce code, ignorez ce mail.\n\n— HiTech Client",
    )
    out = {"ok": True, "delivery": mode}
    if DEV_MODE:
        out["dev_code"] = code  # TEST ONLY — remove when SMTP is live
    return out


def verify_code(store, email: str, code: str) -> dict:
    email = (email or "").strip().lower()
    code = (code or "").strip()
    row = store.get_login_code(email)
    now = int(time.time())
    if not row or row["expires"] < now:
        store.clear_login_code(email)
        raise ValueError("code expiré — demandez-en un nouveau")
    if row["attempts"] >= MAX_ATTEMPTS:
        store.clear_login_code(email)
        raise ValueError("trop d'essais — demandez un nouveau code")
    if not hmac.compare_digest(row["code_hash"], _hash_code(email, code)):
        store.bump_code_attempts(email)
        raise ValueError("code incorrect")
    store.clear_login_code(email)
    user = store.get_or_create_user(email)
    store.touch_login(user["id"])
    token = make_user_token(user["id"], email)
    return {"user": user, "token": token}
