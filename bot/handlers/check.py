from aiogram import Bot, Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery

from bot import db
from bot.keyboards import view_proofs_keyboard
from bot.utils import format_reputation_card, parse_target

router = Router()


class CheckStates(StatesGroup):
    waiting_for_username = State()


@router.message(Command("check"))
async def cmd_check(message: Message, state: FSMContext) -> None:
    await db.upsert_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
    )

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await state.set_state(CheckStates.waiting_for_username)
        await message.answer(
            "Who do you want to check?\n"
            "Send their <code>@username</code> or Telegram user ID.",
            parse_mode="HTML",
        )
        return

    await _do_check(message, args[1].strip())


@router.message(F.text == "\U0001f50d Check User")
async def btn_check(message: Message, state: FSMContext) -> None:
    await db.upsert_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
    )
    await state.set_state(CheckStates.waiting_for_username)
    await message.answer(
        "Who do you want to check?\n"
        "Send their <code>@username</code> or Telegram user ID.",
        parse_mode="HTML",
    )


@router.message(CheckStates.waiting_for_username)
async def process_check_username(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Please send a @username or numeric user ID.")
        return
    await state.clear()
    await _do_check(message, message.text.strip())


async def _do_check(message: Message, raw_target: str) -> None:
    if raw_target.lstrip("@").isdigit():
        target_user = await db.get_user_by_id(int(raw_target.lstrip("@")))
    else:
        target_user = await db.get_user_by_username(parse_target(raw_target))

    if not target_user:
        await message.answer("User not found in our database. They may not have been reviewed yet.")
        return

    positive, negative = await db.count_approved_reviews(target_user["user_id"])
    recent = await db.get_approved_reviews_for_target(target_user["user_id"])
    card = format_reputation_card(target_user, positive, negative, recent)

    if recent:
        await message.answer(card, reply_markup=view_proofs_keyboard(recent))
    else:
        await message.answer(card)


@router.callback_query(F.data.startswith("view_proof:"))
async def view_proof(callback: CallbackQuery, bot: Bot) -> None:
    review_id = int(callback.data.split(":")[1])
    review = await db.get_review(review_id)

    if not review:
        await callback.answer("Review not found.", show_alert=True)
        return

    if review["status"] != "approved":
        await callback.answer("This review is no longer available.", show_alert=True)
        return

    file_id = review["proof_file_id"]
    proof_type = review.get("proof_type", "photo")
    reviewer = await db.get_user_by_id(review["reviewer_id"])
    reviewer_name = f"@{reviewer['username']}" if reviewer and reviewer["username"] else f"ID {review['reviewer_id']}"
    icon = "\u2705" if review["review_type"] == "positive" else "\u274c"

    caption = (
        f"{icon} <b>Proof for Review #{review_id}</b>\n"
        f"<b>By:</b> {reviewer_name}\n"
        f"<b>Comment:</b> {review['comment'][:300]}"
    )

    chat_id = callback.message.chat.id
    try:
        if proof_type == "video":
            await bot.send_video(chat_id=chat_id, video=file_id, caption=caption, parse_mode="HTML")
        elif proof_type == "video_note":
            await bot.send_video_note(chat_id=chat_id, video_note=file_id)
            await bot.send_message(chat_id=chat_id, text=caption, parse_mode="HTML")
        elif proof_type == "document":
            await bot.send_document(chat_id=chat_id, document=file_id, caption=caption, parse_mode="HTML")
        else:
            await bot.send_photo(chat_id=chat_id, photo=file_id, caption=caption, parse_mode="HTML")
    except Exception:
        await callback.answer("Could not load proof media.", show_alert=True)
        return

    await callback.answer()
