from aiogram import Bot, Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from bot import db
from bot.keyboards import appeal_review_keyboard, skip_proof_keyboard
from bot.states import AppealStates
from bot.tracker import track_user

router = Router()


async def _start_appeal(message: Message, state: FSMContext) -> None:
    await track_user(message.bot, message.from_user.id, message.from_user.username, message.from_user.first_name, is_premium=bool(message.from_user.is_premium))

    neg_reviews = await db.get_negative_reviews_for_user(message.from_user.id)
    if not neg_reviews:
        await message.answer("You have no approved negative reviews to appeal.")
        return

    await state.set_state(AppealStates.waiting_for_review_selection)
    await message.answer(
        "Select the negative review you want to appeal:",
        reply_markup=appeal_review_keyboard(neg_reviews),
    )


@router.message(Command("appeal"))
async def cmd_appeal(message: Message, state: FSMContext) -> None:
    await _start_appeal(message, state)


@router.message(F.text == "\U0001f4e8 Appeal")
async def btn_appeal(message: Message, state: FSMContext) -> None:
    await _start_appeal(message, state)


@router.callback_query(AppealStates.waiting_for_review_selection, F.data.startswith("appeal_select:"))
async def select_review(callback: CallbackQuery, state: FSMContext) -> None:
    review_id = int(callback.data.split(":")[1])

    if await db.has_pending_appeal(review_id):
        await callback.answer("You already have a pending appeal for this review.", show_alert=True)
        return

    review = await db.get_review(review_id)
    if not review or review["target_id"] != callback.from_user.id:
        await callback.answer("Invalid review.", show_alert=True)
        return

    await state.update_data(review_id=review_id)
    await state.set_state(AppealStates.waiting_for_comment)
    await callback.message.edit_text(
        f"Appealing Review #{review_id}.\n\n"
        "Write your counter-statement explaining why this review is wrong."
    )
    await callback.answer()


@router.callback_query(AppealStates.waiting_for_review_selection, F.data == "appeal_cancel")
async def cancel_appeal(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("Appeal cancelled.")
    await callback.answer()


@router.message(AppealStates.waiting_for_comment)
async def process_appeal_comment(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Please send a text counter-statement.")
        return

    if len(message.text) < 10:
        await message.answer("Please provide a more detailed statement (at least 10 characters).")
        return

    await state.update_data(comment=message.text)
    await state.set_state(AppealStates.waiting_for_proof)
    await message.answer(
        "Optionally, upload a screenshot or video as counter-evidence.\n"
        "Or press the button below to skip.",
        reply_markup=skip_proof_keyboard(),
    )


@router.callback_query(AppealStates.waiting_for_proof, F.data == "appeal_skip_proof")
async def skip_proof(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await callback.answer()
    await _submit_appeal(callback.message, callback.from_user, state, proof_file_id=None)


@router.message(AppealStates.waiting_for_proof, F.photo)
async def process_appeal_proof_photo(message: Message, state: FSMContext, bot: Bot) -> None:
    file_id = message.photo[-1].file_id
    await _submit_appeal(message, message.from_user, state, proof_file_id=file_id)


@router.message(AppealStates.waiting_for_proof, F.video)
async def process_appeal_proof_video(message: Message, state: FSMContext, bot: Bot) -> None:
    file_id = message.video.file_id
    await _submit_appeal(message, message.from_user, state, proof_file_id=file_id)


@router.message(AppealStates.waiting_for_proof, F.document)
async def process_appeal_proof_doc(message: Message, state: FSMContext, bot: Bot) -> None:
    file_id = message.document.file_id
    await _submit_appeal(message, message.from_user, state, proof_file_id=file_id)


@router.message(AppealStates.waiting_for_proof)
async def process_appeal_proof_invalid(message: Message, state: FSMContext) -> None:
    await message.answer(
        "Please send a photo, video, or document \u2014 or press 'Skip' below.",
        reply_markup=skip_proof_keyboard(),
    )


async def _submit_appeal(message, from_user, state: FSMContext, proof_file_id: str | None) -> None:
    data = await state.get_data()

    await db.create_appeal(
        review_id=data["review_id"],
        appellant_id=from_user.id,
        comment=data["comment"],
        proof_file_id=proof_file_id,
    )
    await state.clear()

    await message.answer(
        "\u2705 Your appeal has been submitted and is pending admin review.\n"
        "You'll be notified once it's processed."
    )
