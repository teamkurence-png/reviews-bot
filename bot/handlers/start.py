from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message

from bot import db
from bot.keyboards import main_menu_keyboard

router = Router()

HELP_TEXT = (
    "\U0001f50d <b>Social Proof Bot</b> — verify Telegram users\n\n"
    "<b>How to use:</b>\n"
    "\U0001f50d <b>Check User</b> — Look up a user's reputation\n"
    "\u270f\ufe0f <b>Write Review</b> — Submit a vouch or negative review (with proof)\n"
    "\U0001f4e8 <b>Appeal</b> — Appeal a negative review against you\n"
    "\u2753 <b>Help</b> — Show this message\n\n"
    "All reviews require a screenshot or video as proof and are verified "
    "by admins before they count toward a user's score."
)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await db.upsert_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
    )
    await message.answer(
        f"Welcome, {message.from_user.first_name}!\n\n{HELP_TEXT}",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )


@router.message(Command("help"))
@router.message(F.text == "\u2753 Help")
async def cmd_help(message: Message) -> None:
    await db.upsert_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
    )
    await message.answer(HELP_TEXT, parse_mode="HTML", reply_markup=main_menu_keyboard())
