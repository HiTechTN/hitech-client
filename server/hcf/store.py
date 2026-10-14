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
            """)
            self._conn.commit()

    # -- sessions ------------------------------------------------------
    def create_session(self, title: str = "Conversation",
                       backend: str = "", model: str = "") -> dict:
        sid = uuid.uuid4().hex[:12]
        ts = _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO sessions VALUES (?,?,?,?,?,?)",
                (sid, title[:120], backend, model, ts, ts))
            self._conn.commit()
        return self.get_session(sid)

    def list_sessions(self, limit: int = 100) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM sessions ORDER BY updated DESC LIMIT ?", (limit,)).fetchall()
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
