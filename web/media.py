from __future__ import annotations

import mimetypes

import aiohttp
from aiohttp import web

from bot.config import BOT_TOKEN


async def proxy_media(request: web.Request) -> web.StreamResponse:
    """Download a file from Telegram servers by file_id and stream it to the browser."""
    file_id = request.match_info["file_id"]
    bot = request.app["bot"]

    try:
        tg_file = await bot.get_file(file_id)
    except Exception:
        raise web.HTTPNotFound(text="File not found on Telegram servers.")

    file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{tg_file.file_path}"

    content_type, _ = mimetypes.guess_type(tg_file.file_path or "")
    if not content_type:
        content_type = "application/octet-stream"

    response = web.StreamResponse(
        status=200,
        headers={"Content-Type": content_type},
    )
    await response.prepare(request)

    async with aiohttp.ClientSession() as session:
        async with session.get(file_url) as upstream:
            async for chunk in upstream.content.iter_chunked(64 * 1024):
                await response.write(chunk)

    await response.write_eof()
    return response
