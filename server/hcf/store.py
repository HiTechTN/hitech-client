"""HCF session store — SQLite (stdlib only). History belongs to HCF,
so switching backends never loses a conversation."""
import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path


def _now() -> int:
    return int(time.time())


class Store:
    def __init__(self, data_dir: str):
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        self.db_path = str(Path(data_dir) / "hcf.sqlite3")
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT DEFAULT 'Conversation',
                    backend TEXT DEFAULT '',
                    model TEXT DEFAULT '',
                    created INTEGER, updated INTEGER
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created INTEGER
                );
                CREATE INDEX IF NOT EXISTS idx_msg_session ON messages(session_id, created);
                CREATE TABLE IF NOT EXISTS session_links (
                    hcf_id TEXT PRIMARY KEY,
                    oc_id TEXT NOT NULL,
                    updated INTEGER
                );
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    name TEXT DEFAULT '',
                    created INTEGER,
                    last_login INTEGER
                );
                CREATE TABLE IF NOT EXISTS login_codes (
                    email TEXT PRIMARY KEY,
                    code_hash TEXT NOT NULL,
                    expires INTEGER,
                    attempts INTEGER DEFAULT 0,
                    sent INTEGER,
                    count_hour INTEGER DEFAULT 0,
                    hour_start INTEGER
                );
            """)
            # migration: per-user sessions
            cols = [r["name"] for r in self._conn.execute("PRAGMA table_info(sessions)")]
            if "user_id" not in cols:
                self._conn.execute("ALTER TABLE sessions ADD COLUMN user_id TEXT DEFAULT ''")
            self._conn.commit()

    # -- sessions ------------------------------------------------------
    def create_session(self, title: str = "Conversation",
                       backend: str = "", model: str = "",
                       user_id: str = "") -> dict:
        sid = uuid.uuid4().hex[:12]
        ts = _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO sessions (id, title, backend, model, created, updated, user_id) VALUES (?,?,?,?,?,?,?)",
                (sid, title[:120], backend, model, ts, ts, user_id))
            self._conn.commit()
        return self.get_session(sid)

    def list_sessions(self, limit: int = 100,
                      user_id: str | None = None) -> list[dict]:
        with self._lock:
            if user_id is None:
                rows = self._conn.execute(
                    "SELECT * FROM sessions ORDER BY updated DESC LIMIT ?", (limit,)).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM sessions WHERE user_id=? ORDER BY updated DESC LIMIT ?",
                    (user_id, limit)).fetchall()
        return [dict(r) for r in rows]

    def get_session(self, sid: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
        return dict(row) if row else None

    def update_session(self, sid: str, **fields) -> dict | None:
        allowed = {"title", "backend", "model"}
        sets = [f"{k}=?" for k in fields if k in allowed]
        if not sets:
            return self.get_session(sid)
        vals = [str(fields[k])[:120] if k == "title" else fields[k]
                for k in fields if k in allowed]
        with self._lock:
            self._conn.execute(
                f"UPDATE sessions SET {', '.join(sets)}, updated=? WHERE id=?",
                (*vals, _now(), sid))
            self._conn.commit()
        return self.get_session(sid)

    def delete_session(self, sid: str) -> bool:
        with self._lock:
            self._conn.execute("DELETE FROM messages WHERE session_id=?", (sid,))
            self._conn.execute("DELETE FROM session_links WHERE hcf_id=?", (sid,))
            cur = self._conn.execute("DELETE FROM sessions WHERE id=?", (sid,))
            self._conn.commit()
        return cur.rowcount > 0

    # -- users & login codes ---------------------------------------------
    def get_or_create_user(self, email: str) -> dict:
        email = email.strip().lower()
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM users WHERE email=?", (email,)).fetchone()
            if not row:
                uid = uuid.uuid4().hex[:12]
                self._conn.execute(
                    "INSERT INTO users VALUES (?,?,?,?,?)",
                    (uid, email, "", _now(), _now()))
                self._conn.commit()
                row = self._conn.execute(
                    "SELECT * FROM users WHERE email=?", (email,)).fetchone()
        return dict(row)

    def get_user(self, uid: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        return dict(row) if row else None

    def touch_login(self, uid: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE users SET last_login=? WHERE id=?", (_now(), uid))
            self._conn.commit()

    def get_login_code(self, email: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM login_codes WHERE email=?",
                (email.strip().lower(),)).fetchone()
        return dict(row) if row else None

    def save_login_code(self, email: str, code_hash: str,
                        expires: int, sent: int) -> None:
        email = email.strip().lower()
        with self._lock:
            old = self._conn.execute(
                "SELECT count_hour, hour_start FROM login_codes WHERE email=?",
                (email,)).fetchone()
            now = sent
            if old and now - (old["hour_start"] or 0) < 3600:
                ch, hs = old["count_hour"] + 1, old["hour_start"]
            else:
                ch, hs = 1, now
            self._conn.execute(
                "INSERT OR REPLACE INTO login_codes VALUES (?,?,?,?,?,?,?)",
                (email, code_hash, expires, 0, sent, ch, hs))
            self._conn.commit()

    def bump_code_attempts(self, email: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE login_codes SET attempts=attempts+1 WHERE email=?",
                (email.strip().lower(),))
            self._conn.commit()

    def clear_login_code(self, email: str) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM login_codes WHERE email=?", (email.strip().lower(),))
            self._conn.commit()

    # -- backend session links (e.g. HCF sid -> OpenCode sid) -------------
    def get_link(self, hcf_id: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT oc_id FROM session_links WHERE hcf_id=?", (hcf_id,)).fetchone()
        return row["oc_id"] if row else None

    def set_link(self, hcf_id: str, oc_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO session_links VALUES (?,?,?)",
                (hcf_id, oc_id, _now()))
            self._conn.commit()

    # -- messages ------------------------------------------------------
    def add_message(self, session_id: str, role: str, content: list[dict]) -> dict:
        mid = uuid.uuid4().hex[:12]
        ts = _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO messages VALUES (?,?,?,?,?)",
                (mid, session_id, role, json.dumps(content), ts))
            self._conn.execute(
                "UPDATE sessions SET updated=? WHERE id=?", (ts, session_id))
            self._conn.commit()
        return {"id": mid, "session_id": session_id, "role": role,
                "content": content, "created": ts}

    def list_messages(self, session_id: str, limit: int = 200) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM messages WHERE session_id=? ORDER BY created ASC LIMIT ?",
                (session_id, limit)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["content"] = json.loads(d["content"])
            except (ValueError, TypeError):
                d["content"] = [{"type": "text", "text": str(d["content"])}]
            out.append(d)
        return out
