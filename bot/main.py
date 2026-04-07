import asyncio
import logging
import sys

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from bot.config import BOT_TOKEN, WEB_PORT
from bot.db import init_db, close_db
from bot.handlers import start, check, review, appeal, reference
from web.app import create_web_app

BOT_COMMANDS = [
    BotCommand(command="start", description="Start the bot"),
    BotCommand(command="check", description="Look up a user's reputation"),
    BotCommand(command="review", description="Submit a vouch or negative review"),
    BotCommand(command="addref", description="Add references for a user"),
    BotCommand(command="appeal", description="Appeal a negative review against you"),
    BotCommand(command="help", description="Show help"),
]


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )

    await init_db()

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=None))
    dp = Dispatcher(storage=MemoryStorage())

    await bot.set_my_commands(BOT_COMMANDS)

    dp.include_routers(
        start.router,
        check.router,
        review.router,
        reference.router,
        appeal.router,
    )

    bot_info = await bot.get_me()
    bot_username = bot_info.username

    webapp = create_web_app(bot, bot_username)
    runner = web.AppRunner(webapp)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", WEB_PORT)
    await site.start()
    logging.info("Web admin panel running on http://localhost:%d", WEB_PORT)

    try:
        logging.info("Bot started — polling...")
        await dp.start_polling(bot)
    finally:
        await runner.cleanup()
        await close_db()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
