from aiogram import Bot, Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup

from bot import db
from bot.keyboards import view_proofs_keyboard, check_history_keyboard
from bot.tracker import track_user, track_target_photo
from bot.utils import format_reputation_card, parse_target

router = Router()


class CheckStates(StatesGroup):
    waiting_for_username = State()


@router.message(Command("check"))
async def cmd_check(message: Message, state: FSMContext, bot: Bot) -> None:
    await track_user(bot, message.from_user.id, message.from_user.username, message.from_user.first_name, is_premium=bool(message.from_user.is_premium))

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
async def btn_check(message: Message, state: FSMContext, bot: Bot) -> None:
    await track_user(bot, message.from_user.id, message.from_user.username, message.from_user.first_name, is_premium=bool(message.from_user.is_premium))
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
    is_numeric = raw_target.lstrip("@").isdigit()

    if is_numeric:
        target_user = await db.get_user_by_id(int(raw_target.lstrip("@")))
    else:
        target_user = await db.get_user_by_username(parse_target(raw_target))

    if not target_user:
        if is_numeric:
            numeric_id = int(raw_target.lstrip("@"))
            try:
                chat = await message.bot.get_chat(numeric_id)
                is_premium = bool(getattr(chat, "is_premium", False))
                await db.upsert_user(
                    chat.id,
                    chat.username,
                    chat.first_name,
                    is_premium=is_premium,
                )
                target_user = await db.get_user_by_id(chat.id)
            except Exception:
                pass

        if not target_user:
            username = parse_target(raw_target)
            target_user = await db.get_or_create_user_by_username(username)

    target_id = target_user["user_id"]

    await track_target_photo(message.bot, target_id)

    positive, negative = await db.count_approved_reviews(target_id)
    recent = await db.get_approved_reviews_for_target(target_id)
    first_review_date = await db.get_first_review_date(target_id)
    references = await db.get_approved_refs_for_target(target_id)
    changes = await db.get_user_changes(target_id)
    photo_count = await db.count_user_photos(target_id)

    card = format_reputation_card(
        target_user, positive, negative, recent,
        first_review_date, references, changes, photo_count,
    )

    buttons = []
    if recent:
        buttons.extend(view_proofs_keyboard(recent).inline_keyboard)
    if photo_count > 0:
        buttons.extend(check_history_keyboard(target_id).inline_keyboard)

    if buttons:
        await message.answer(card, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    else:
        await message.answer(card, parse_mode="HTML")


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

    proofs = await db.get_review_proofs(review_id)
    if not proofs:
        proofs = [{"file_id": review["proof_file_id"], "proof_type": review.get("proof_type", "photo")}]

    reviewer = await db.get_user_by_id(review["reviewer_id"])
    reviewer_name = f"@{reviewer['username']}" if reviewer and reviewer["username"] else f"ID {review['reviewer_id']}"
    icon = "\u2705" if review["review_type"] == "positive" else "\u274c"
    chat_id = callback.message.chat.id

    total = len(proofs)
    for idx, proof in enumerate(proofs, 1):
        file_id = proof["file_id"]
        proof_type = proof.get("proof_type", "photo")
        counter = f" ({idx}/{total})" if total > 1 else ""

        caption = (
            f"{icon} <b>Proof for Review #{review_id}{counter}</b>\n"
            f"<b>By:</b> {reviewer_name}\n"
            f"<b>Comment:</b> {review['comment'][:300]}"
        )

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


@router.callback_query(F.data.startswith("view_photos:"))
async def view_old_photos(callback: CallbackQuery, bot: Bot) -> None:
    target_id = int(callback.data.split(":")[1])
    photos = await db.get_user_photos(target_id)

    if not photos:
        await callback.answer("No profile photos tracked for this user.", show_alert=True)
        return

    target_user = await db.get_user_by_id(target_id)
    name = f"@{target_user['username']}" if target_user and target_user["username"] else f"ID {target_id}"
    chat_id = callback.message.chat.id

    await bot.send_message(
        chat_id,
        f"\U0001f4f8 <b>Profile photo history for {name}</b> — {len(photos)} photo{'s' if len(photos) != 1 else ''} tracked:",
        parse_mode="HTML",
    )

    for idx, photo in enumerate(photos, 1):
        detected = photo["detected_at"][:16] if photo.get("detected_at") else "unknown"
        caption = f"Photo #{idx} — first seen {detected}"
        try:
            await bot.send_photo(chat_id=chat_id, photo=photo["file_id"], caption=caption)
        except Exception:
            await bot.send_message(chat_id=chat_id, text=f"Photo #{idx} — could not load (file may have expired)")

    await callback.answer()
