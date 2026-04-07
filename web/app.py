from __future__ import annotations

from pathlib import Path

import aiohttp_jinja2
import jinja2
from aiohttp import web

from web.auth import auth_middleware
from web.media import proxy_media
from web.views import (
    login_page,
    login_submit,
    logout,
    dashboard,
    reviews_list,
    approve_review,
    reject_review,
    appeals_list,
    uphold_appeal,
    overturn_appeal,
    refs_list,
    approve_ref,
    reject_ref,
)

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


def create_web_app(bot, bot_username: str) -> web.Application:
    app = web.Application(middlewares=[auth_middleware])
    app["bot"] = bot
    app["bot_username"] = bot_username

    aiohttp_jinja2.setup(
        app,
        loader=jinja2.FileSystemLoader(str(TEMPLATES_DIR)),
        context_processors=[aiohttp_jinja2.request_processor],
    )

    app.router.add_get("/login", login_page)
    app.router.add_post("/login", login_submit)
    app.router.add_get("/logout", logout)
    app.router.add_get("/", dashboard)
    app.router.add_get("/reviews", reviews_list)
    app.router.add_post("/reviews/{id}/approve", approve_review)
    app.router.add_post("/reviews/{id}/reject", reject_review)
    app.router.add_get("/appeals", appeals_list)
    app.router.add_post("/appeals/{id}/uphold", uphold_appeal)
    app.router.add_post("/appeals/{id}/overturn", overturn_appeal)
    app.router.add_get("/references", refs_list)
    app.router.add_post("/references/{id}/approve", approve_ref)
    app.router.add_post("/references/{id}/reject", reject_ref)
    app.router.add_get("/media/{file_id}", proxy_media)

    return app
