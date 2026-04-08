"""Profile change tracker.

Detects and logs changes to Telegram usernames, display names, and
profile photos each time the bot encounters a user.
"""
from __future__ import annotations

from aiogram import Bot

from bot import db


async def track_user(
    bot: Bot,
    user_id: int,
    username: str | None,
    first_name: str | None,
    *,
    is_premium: bool = False,
    check_photo: bool = True,
) -> None:
    """Compare current profile info against stored data, log any diffs,
    then upsert the user record.

    If a placeholder record exists for this username (negative ID from a
    review submitted before the user interacted with the bot), all data is
    merged into the real user record automatically.

    ``check_photo`` can be disabled to skip the API call when it's not
    needed (e.g. high-frequency handlers).
    """
    if username and user_id > 0:
        placeholder = await db.get_user_by_username(username)
        if placeholder and placeholder["user_id"] < 0:
            await db.merge_placeholder(placeholder["user_id"], user_id)

    existing = await db.get_user_by_id(user_id)

    if existing:
        old_username = existing["username"]
        old_name = existing["first_name"]

        if old_username != username and not (old_username is None and username is None):
            await db.log_user_change(user_id, "username", old_username, username)

        if old_name != first_name and not (old_name is None and first_name is None):
            await db.log_user_change(user_id, "name", old_name, first_name)

    if check_photo and user_id > 0:
        await _track_photo(bot, user_id, is_first=(existing is None))

    await db.upsert_user(user_id, username, first_name, is_premium=is_premium)


async def track_target_photo(bot: Bot, user_id: int) -> None:
    """Attempt to snapshot a target user's current profile photo.

    Called during /check so we capture photo history even for users who
    don't interact with the bot directly.  Silently skips placeholder
    (negative) IDs.
    """
    if user_id <= 0:
        return
    existing = await db.get_user_by_id(user_id)
    await _track_photo(bot, user_id, is_first=(existing is None))


async def _track_photo(bot: Bot, user_id: int, *, is_first: bool) -> None:
    try:
        photos = await bot.get_user_profile_photos(user_id, limit=5)
    except Exception:
        return

    if photos.total_count == 0:
        return

    for photo_sizes in photos.photos:
        largest = photo_sizes[-1]
        was_new = await db.track_user_photo(
            user_id, largest.file_id, largest.file_unique_id,
        )
        if was_new and not is_first:
            await db.log_user_change(user_id, "photo", None, largest.file_unique_id)
