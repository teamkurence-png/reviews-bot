from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="\U0001f50d Check User"), KeyboardButton(text="\u270f\ufe0f Write Review")],
            [KeyboardButton(text="\U0001f4e8 Appeal"), KeyboardButton(text="\u2753 Help")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Choose an action...",
    )


def review_type_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="\u2705 Vouch", callback_data="review_type:positive"),
            InlineKeyboardButton(text="\u274c Negative", callback_data="review_type:negative"),
        ]
    ])


def appeal_review_keyboard(reviews: list[dict]) -> InlineKeyboardMarkup:
    buttons = []
    for r in reviews:
        reviewer = r.get("reviewer_username") or str(r["reviewer_id"])
        label = f"Review #{r['id']} by @{reviewer}"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"appeal_select:{r['id']}")])
    buttons.append([InlineKeyboardButton(text="Cancel", callback_data="appeal_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def skip_proof_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Skip (no screenshot)", callback_data="appeal_skip_proof")]
    ])


def view_proofs_keyboard(reviews: list[dict]) -> InlineKeyboardMarkup:
    buttons = []
    for r in reviews:
        icon = "\u2705" if r["review_type"] == "positive" else "\u274c"
        reviewer = r.get("reviewer_username") or str(r["reviewer_id"])
        label = f"{icon} View proof — Review #{r['id']} by @{reviewer}"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"view_proof:{r['id']}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
