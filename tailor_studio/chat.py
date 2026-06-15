"""Single platform-wide team group chat: connection manager + persistence.

One shared room for every logged-in account (owner + bidders). Real-time
delivery is via WebSocket (see /ws/chat in main.py); history is persisted in
the chat_message table and served over REST for the initial page load.

This assumes a single uvicorn worker (the default here) — the connection
registry is in-process. Multi-worker would need a pub/sub backend (e.g. Redis).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

from fastapi import WebSocket

from .db import ChatMessage


def _iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def display_name(email: str, name: Optional[str] = None) -> str:
    if name and name.strip():
        return name.strip()
    return (email or "").split("@")[0] or "member"


def reply_snippet(db, reply_to_id: Optional[int]) -> Optional[dict]:
    """Compact view of a quoted message, for rendering the quote block."""
    if not reply_to_id:
        return None
    r = db.get(ChatMessage, reply_to_id)
    if r is None:
        return None
    return {"id": r.id, "name": r.sender_name or "member", "body": (r.body or "")[:160]}


def message_payload(m: ChatMessage, reply: Optional[dict] = None) -> dict:
    return {
        "type": "message",
        "id": m.id,
        "user_id": m.user_id,
        "name": m.sender_name or "member",
        "body": m.body,
        "reply_to": reply,
        "created_at": _iso(m.created_at),
    }


def save_message(db, user_id: int, sender_name: str, body: str,
                 reply_to_id: Optional[int] = None) -> ChatMessage:
    # Drop a dangling reply reference rather than failing the FK.
    if reply_to_id and db.get(ChatMessage, reply_to_id) is None:
        reply_to_id = None
    m = ChatMessage(user_id=user_id, sender_name=sender_name, body=body,
                    reply_to_id=reply_to_id)
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


class ConnectionManager:
    def __init__(self) -> None:
        # ws -> {"id": int, "name": str}
        self._conns: dict[WebSocket, dict] = {}
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket, user: dict) -> None:
        await ws.accept()
        async with self._lock:
            self._conns[ws] = user

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._conns.pop(ws, None)

    def presence_payload(self) -> dict:
        # Unique online member names (a member may have several tabs open).
        seen: dict[int, str] = {}
        for u in self._conns.values():
            seen[u["id"]] = u["name"]
        return {"type": "presence", "online": len(seen), "users": sorted(seen.values())}

    async def broadcast(self, payload: dict) -> None:
        dead: list[WebSocket] = []
        for ws in list(self._conns.keys()):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._conns.pop(ws, None)


manager = ConnectionManager()
