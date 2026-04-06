from aiogram import Bot, Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from bot import db
from bot.config import REVIEW_COOLDOWN_HOURS
from bot.keyboards import review_type_keyboard
from bot.states import ReviewStates
from bot.utils import parse_target, check_cooldown

router = Router()


async def _start_review(message: Message, state: FSMContext) -> None:
    await db.upsert_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
    )
    await state.set_state(ReviewStates.waiting_for_target)
    await message.answer(
        "Who do you want to review?\n"
        "Send their <code>@username</code> or Telegram user ID.",
        parse_mode="HTML",
    )


@router.message(Command("review"))
async def cmd_review(message: Message, state: FSMContext) -> None:
    await _start_review(message, state)


@router.message(F.text == "\u270f\ufe0f Write Review")
async def btn_review(message: Message, state: FSMContext) -> None:
    await _start_review(message, state)


@router.message(ReviewStates.waiting_for_target)
async def process_target(message: Message, state: FSMContext) -> None:
    raw = message.text
    if not raw:
        await message.answer("Please send a @username or numeric user ID.")
        return

    clean = parse_target(raw)

    if clean.isdigit():
        target_id = int(clean)
        target_user = await db.get_user_by_id(target_id)
        if not target_user:
            await db.upsert_user(target_id, None, None)
            target_user = await db.get_user_by_id(target_id)
    else:
        target_user = await db.get_or_create_user_by_username(clean)

    if target_user["user_id"] == message.from_user.id:
        await message.answer("You cannot review yourself.")
        return

    if await check_cooldown(message.from_user.id, target_user["user_id"], REVIEW_COOLDOWN_HOURS):
        await message.answer(
            f"You already reviewed this user in the last {REVIEW_COOLDOWN_HOURS} hours. "
            "Please wait before submitting another review."
        )
        await state.clear()
        return

    await state.update_data(target_id=target_user["user_id"])
    target_display = f"@{target_user['username']}" if target_user["username"] else f"ID {target_user['user_id']}"
    await state.set_state(ReviewStates.waiting_for_type)
    await message.answer(
        f"Reviewing <b>{target_display}</b>.\nIs this a vouch or a negative review?",
        parse_mode="HTML",
        reply_markup=review_type_keyboard(),
    )


@router.callback_query(ReviewStates.waiting_for_type, F.data.startswith("review_type:"))
async def process_type(callback: CallbackQuery, state: FSMContext) -> None:
    review_type = callback.data.split(":")[1]
    await state.update_data(review_type=review_type)
    await state.set_state(ReviewStates.waiting_for_comment)
    label = "vouch" if review_type == "positive" else "negative review"
    await callback.message.edit_text(
        f"You chose: <b>{label}</b>.\n\n"
        "Now write a brief description explaining your experience.",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(ReviewStates.waiting_for_comment)
async def process_comment(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Please send a text description.")
        return

    if len(message.text) < 10:
        await message.answer("Please provide a more detailed description (at least 10 characters).")
        return

    await state.update_data(comment=message.text)
    await state.set_state(ReviewStates.waiting_for_proof)
    await message.answer(
        "\U0001f4f8 Now upload <b>proof</b> \u2014 a screenshot, photo, video, or document.\n"
        "This is mandatory to submit a review.",
        parse_mode="HTML",
    )


@router.message(ReviewStates.waiting_for_proof, F.photo)
async def process_proof_photo(message: Message, state: FSMContext, bot: Bot) -> None:
    file_id = message.photo[-1].file_id
    await _submit_review(message, state, file_id, media_type="photo")


@router.message(ReviewStates.waiting_for_proof, F.video)
async def process_proof_video(message: Message, state: FSMContext, bot: Bot) -> None:
    file_id = message.video.file_id
    await _submit_review(message, state, file_id, media_type="video")


@router.message(ReviewStates.waiting_for_proof, F.video_note)
async def process_proof_video_note(message: Message, state: FSMContext, bot: Bot) -> None:
    file_id = message.video_note.file_id
    await _submit_review(message, state, file_id, media_type="video_note")


@router.message(ReviewStates.waiting_for_proof, F.document)
async def process_proof_document(message: Message, state: FSMContext, bot: Bot) -> None:
    file_id = message.document.file_id
    await _submit_review(message, state, file_id, media_type="document")


@router.message(ReviewStates.waiting_for_proof)
async def process_proof_invalid(message: Message, state: FSMContext) -> None:
    await message.answer(
        "Please upload <b>proof</b> \u2014 a screenshot, photo, video, or document.\n"
        "This is mandatory to submit a review.",
        parse_mode="HTML",
    )


async def _submit_review(
    message: Message, state: FSMContext, proof_file_id: str, media_type: str
) -> None:
    data = await state.get_data()

    await db.create_review(
        reviewer_id=message.from_user.id,
        target_id=data["target_id"],
        review_type=data["review_type"],
        comment=data["comment"],
        proof_file_id=proof_file_id,
        proof_type=media_type,
    )

    await state.clear()

    await message.answer(
        "\u2705 Your review has been submitted and is pending admin verification.\n"
        "You'll be notified once it's processed."
    )
