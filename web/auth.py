from __future__ import annotations

import hashlib
import hmac
import json

from aiohttp import web

from bot.config import BOT_TOKEN, ADMIN_PASSWORD

_SECRET = hashlib.sha256(BOT_TOKEN.encode()).digest()
_COOKIE_NAME = "admin_session"


def _sign_cookie(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":"))
    sig = hmac.new(_SECRET, raw.encode(), hashlib.sha256).hexdigest()[:16]
    return f"{raw}|{sig}"


def _verify_cookie(value: str) -> dict | None:
    if "|" not in value:
        return None
    raw, sig = value.rsplit("|", 1)
    expected = hmac.new(_SECRET, raw.encode(), hashlib.sha256).hexdigest()[:16]
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def set_admin_cookie(response: web.Response) -> None:
    payload = {"logged_in": True}
    response.set_cookie(
        _COOKIE_NAME, _sign_cookie(payload),
        max_age=86400 * 7, httponly=True, samesite="Lax",
    )


def get_admin_from_request(request: web.Request) -> dict | None:
    cookie = request.cookies.get(_COOKIE_NAME)
    if not cookie:
        return None
    return _verify_cookie(cookie)


def clear_admin_cookie(response: web.Response) -> None:
    response.del_cookie(_COOKIE_NAME)


def check_password(password: str) -> bool:
    return password == ADMIN_PASSWORD


@web.middleware
async def auth_middleware(request: web.Request, handler):
    if request.path == "/login":
        return await handler(request)

    admin = get_admin_from_request(request)
    if not admin:
        raise web.HTTPFound("/login")

    request["admin"] = admin
    return await handler(request)
