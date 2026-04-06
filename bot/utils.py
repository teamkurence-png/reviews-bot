from __future__ import annotations

from bot import db


def format_reputation_card(
    user: dict,
    positive: int,
    negative: int,
    recent_reviews: list[dict],
) -> str:
    risk_badge = "\u26a0\ufe0f HIGH RISK " if user["is_high_risk"] else ""
    username_display = f"@{user['username']}" if user["username"] else f"ID {user['user_id']}"

    lines = [
        f"{risk_badge}\U0001f464 {username_display}",
        f"\U0001f4ca Reputation score: {user['reputation_score']}",
        f"\u2705 Vouches: {positive}  |  \u274c Negatives: {negative}",
    ]

    if recent_reviews:
        lines.append("")
        lines.append("\U0001f4dd Recent reviews:")
        for r in recent_reviews[:3]:
            icon = "\u2705" if r["review_type"] == "positive" else "\u274c"
            reviewer = r.get("reviewer_username") or str(r["reviewer_id"])
            comment_preview = r["comment"][:80]
            lines.append(f"  {icon} @{reviewer}: {comment_preview}")

    return "\n".join(lines)


def parse_target(text: str) -> str:
    """Extract a clean username from user input, stripping leading @."""
    cleaned = text.strip().lstrip("@")
    return cleaned


async def check_cooldown(reviewer_id: int, target_id: int, hours: int) -> bool:
    """Return True if the reviewer is still within the cooldown period."""
    return await db.has_recent_review(reviewer_id, target_id, hours)
