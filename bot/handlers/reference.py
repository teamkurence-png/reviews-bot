from aiogram import Bot, Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from bot import db
from bot.keyboards import ref_proof_done_keyboard, add_another_ref_keyboard
from bot.states import ReferenceStates
from bot.tracker import track_user
from bot.utils import parse_target

router = Router()


async def _start_addref(message: Message, state: FSMContext) -> None:
    await track_user(message.bot, message.from_user.id, message.from_user.username, message.from_user.first_name)
    await state.update_data(pending_refs=[])
    await state.set_state(ReferenceStates.waiting_for_target)
    await message.answer(
        "\U0001f517 <b>Add Reference</b>\n\n"
        "Who do you want to attach references to?\n"
        "Send their <code>@username</code> or Telegram user ID.",
        parse_mode="HTML",
    )


@router.message(Command("addref"))
async def cmd_addref(message: Message, state: FSMContext) -> None:
    await _start_addref(message, state)


@router.message(F.text == "\U0001f517 Add Reference")
async def btn_addref(message: Message, state: FSMContext) -> None:
    await _start_addref(message, state)


@router.message(ReferenceStates.waiting_for_target)
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

    await state.update_data(target_id=target_user["user_id"])
    target_display = f"@{target_user['username']}" if target_user["username"] else f"ID {target_user['user_id']}"

    await state.set_state(ReferenceStates.waiting_for_ref_username)
    await message.answer(
        f"Adding references for <b>{target_display}</b>.\n\n"
        "Send the <code>@username</code> of the reference person "
        "(the Telegram user who can vouch for them).",
        parse_mode="HTML",
    )


@router.message(ReferenceStates.waiting_for_ref_username)
async def process_ref_username(message: Message, state: FSMContext) -> None:
    raw = message.text
    if not raw:
        await message.answer("Please send the reference person's @username.")
        return

    ref_username = parse_target(raw)
    if not ref_username:
        await message.answer("Please send a valid @username.")
        return

    await state.update_data(current_ref_username=ref_username, current_ref_proofs=[])
    await state.set_state(ReferenceStates.waiting_for_proof)
    await message.answer(
        f"Reference: <b>@{ref_username}</b>\n\n"
        "\U0001f4f8 Now upload <b>proof</b> that this person is a legitimate reference \u2014 "
        "screenshots of conversations, transactions, or any evidence.\n"
        "You can send <b>multiple files</b>. Press <b>Done</b> when finished.",
        parse_mode="HTML",
    )


def _extract_media(message: Message) -> tuple[str, str] | None:
    if message.photo:
        return message.photo[-1].file_id, "photo"
    if message.video:
        return message.video.file_id, "video"
    if message.video_note:
        return message.video_note.file_id, "video_note"
    if message.document:
        return message.document.file_id, "document"
    return None


async def _ack_ref_proof(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    count = len(data.get("current_ref_proofs", []))
    await message.answer(
        f"\u2705 Proof #{count} received! Send more, or press <b>Done</b>.",
        parse_mode="HTML",
        reply_markup=ref_proof_done_keyboard(count),
    )


@router.message(ReferenceStates.waiting_for_proof, F.photo)
async def process_proof_photo(message: Message, state: FSMContext, bot: Bot) -> None:
    file_id = message.photo[-1].file_id
    data = await state.get_data()
    proofs = data.get("current_ref_proofs", []) + [{"file_id": file_id, "proof_type": "photo"}]
    await state.update_data(current_ref_proofs=proofs)
    await _ack_ref_proof(message, state)


@router.message(ReferenceStates.waiting_for_proof, F.video)
async def process_proof_video(message: Message, state: FSMContext, bot: Bot) -> None:
    file_id = message.video.file_id
    data = await state.get_data()
    proofs = data.get("current_ref_proofs", []) + [{"file_id": file_id, "proof_type": "video"}]
    await state.update_data(current_ref_proofs=proofs)
    await _ack_ref_proof(message, state)


@router.message(ReferenceStates.waiting_for_proof, F.video_note)
async def process_proof_video_note(message: Message, state: FSMContext, bot: Bot) -> None:
    file_id = message.video_note.file_id
    data = await state.get_data()
    proofs = data.get("current_ref_proofs", []) + [{"file_id": file_id, "proof_type": "video_note"}]
    await state.update_data(current_ref_proofs=proofs)
    await _ack_ref_proof(message, state)


@router.message(ReferenceStates.waiting_for_proof, F.document)
async def process_proof_document(message: Message, state: FSMContext, bot: Bot) -> None:
    file_id = message.document.file_id
    data = await state.get_data()
    proofs = data.get("current_ref_proofs", []) + [{"file_id": file_id, "proof_type": "document"}]
    await state.update_data(current_ref_proofs=proofs)
    await _ack_ref_proof(message, state)


@router.message(ReferenceStates.waiting_for_proof)
async def process_proof_invalid(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    count = len(data.get("current_ref_proofs", []))
    if count > 0:
        await message.answer(
            "That's not a supported media type. Send a photo, video, or document, "
            "or press <b>Done</b>.",
            parse_mode="HTML",
            reply_markup=ref_proof_done_keyboard(count),
        )
    else:
        await message.answer(
            "Please upload <b>proof</b> \u2014 a screenshot, photo, video, or document.\n"
            "At least one proof is required per reference.",
            parse_mode="HTML",
        )


@router.callback_query(ReferenceStates.waiting_for_proof, F.data == "ref_proof_done")
async def process_proof_done(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    proofs = data.get("current_ref_proofs", [])

    if not proofs:
        await callback.answer("You need at least one proof.", show_alert=True)
        return

    ref_username = data["current_ref_username"]
    pending = data.get("pending_refs", [])
    pending.append({"ref_username": ref_username, "proofs": proofs})
    await state.update_data(
        pending_refs=pending,
        current_ref_username=None,
        current_ref_proofs=[],
    )

    count = len(pending)
    ref_list = "\n".join(f"  \U0001f517 @{r['ref_username']} ({len(r['proofs'])} proof{'s' if len(r['proofs']) != 1 else ''})" for r in pending)

    await callback.message.edit_text(
        f"\u2705 Reference <b>@{ref_username}</b> saved with {len(proofs)} proof{'s' if len(proofs) != 1 else ''}.\n\n"
        f"<b>References queued ({count}):</b>\n{ref_list}\n\n"
        "Add another reference, or submit all for admin review.",
        parse_mode="HTML",
        reply_markup=add_another_ref_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "ref_add_another")
async def add_another_ref(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ReferenceStates.waiting_for_ref_username)
    await callback.message.edit_text(
        "Send the <code>@username</code> of the next reference person.",
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "ref_submit_all")
async def submit_all_refs(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    pending = data.get("pending_refs", [])

    if not pending:
        await callback.answer("No references to submit.", show_alert=True)
        return

    target_id = data["target_id"]
    submitter_id = callback.from_user.id

    for ref in pending:
        await db.create_reference(
            submitter_id=submitter_id,
            target_id=target_id,
            ref_username=ref["ref_username"],
            proofs=ref["proofs"],
        )

    await state.clear()

    count = len(pending)
    await callback.message.edit_text(
        f"\u2705 <b>{count} reference{'s' if count != 1 else ''}</b> submitted "
        "and pending admin verification.\n"
        "You'll be notified once they're processed.",
        parse_mode="HTML",
    )
    await callback.answer()
