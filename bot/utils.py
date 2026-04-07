from __future__ import annotations

from datetime import datetime, timezone

from bot import db


def compute_trust_score(positive: int, negative: int) -> tuple[int, str, str]:
    """Return (score 0-100, color_indicator, label)."""
    score = 50 + min(positive * 8, 45) - (negative * 15)
    score = max(0, min(100, score))

    if score <= 15:
        return score, "\U0001f534", "Dangerous"
    elif score <= 30:
        return score, "\U0001f7e0", "Suspicious"
    elif score <= 45:
        return score, "\U0001f7e1", "Caution"
    elif score <= 60:
        return score, "\u26aa", "Neutral"
    elif score <= 75:
        return score, "\U0001f7e2", "Reputable"
    else:
        return score, "\U0001f7e2", "Trusted"


def _account_status(positive: int, negative: int, is_high_risk: bool) -> tuple[str, str]:
    """Return (icon, status_label)."""
    if is_high_risk:
        return "\U0001f6a8", "HIGH RISK"
    if negative == 0:
        return "\u2705", "Clean"
    if positive > 0 and negative > 0:
        return "\u26a0\ufe0f", "Disputed"
    return "\U0001f6a9", "Flagged"


def _time_ago(date_str: str) -> str:
    """Convert a datetime string to a human-readable 'X ago' format."""
    try:
        dt = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = now - dt
        seconds = int(delta.total_seconds())

        if seconds < 60:
            return "just now"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes}m ago"
        hours = minutes // 60
        if hours < 24:
            return f"{hours}h ago"
        days = hours // 24
        if days < 7:
            return f"{days}d ago"
        weeks = days // 7
        if weeks < 5:
            return f"{weeks}w ago"
        months = days // 30
        if months < 12:
            return f"{months}mo ago"
        return f"{days // 365}y ago"
    except Exception:
        return ""


def format_reputation_card(
    user: dict,
    positive: int,
    negative: int,
    recent_reviews: list[dict],
    first_review_date: str | None = None,
    references: list[dict] | None = None,
    changes: list[dict] | None = None,
    photo_count: int = 0,
) -> str:
    name = user.get("first_name") or "Unknown"
    username = f"@{user['username']}" if user["username"] else "N/A"
    user_id = user["user_id"]

    trust_score, trust_icon, trust_label = compute_trust_score(positive, negative)
    status_icon, status_label = _account_status(positive, negative, bool(user["is_high_risk"]))

    total = positive + negative
    net = positive - negative
    net_str = f"+{net}" if net > 0 else str(net)

    risk_line = "\U0001f6a8 HIGH RISK \u2014 multiple verified negative reviews" if user["is_high_risk"] else "None"

    lines = [
        "\u2501" * 24,
        "   \U0001f4ca  <b>REPUTATION REPORT</b>",
        "\u2501" * 24,
        "",
        f"\U0001f464 <b>Name:</b> {name}",
        f"\U0001f4db <b>Username:</b> {username}",
        f"\U0001f194 <b>ID:</b> <code>{user_id}</code>",
        "",
        f"{trust_icon} <b>Trust Level:</b> {trust_label} ({trust_score}/100)",
        f"{status_icon} <b>Account Status:</b> {status_label}",
        f"\U0001f6a9 <b>Risk Flag:</b> {risk_line}",
        "",
        "\u2500\u2500\u2500 <b>Review Summary</b> \u2500\u2500\u2500",
        f"\U0001f44d <b>Positive:</b> {positive}",
        f"\U0001f44e <b>Negative:</b> {negative}",
        f"\U0001f4cb <b>Total Reviews:</b> {total}",
        f"\U0001f4c8 <b>Score:</b> {net_str}",
    ]

    if recent_reviews:
        lines.append("")
        lines.append("\u2500\u2500\u2500 <b>Recent Activity</b> \u2500\u2500\u2500")
        for r in recent_reviews[:5]:
            icon = "\U0001f44d" if r["review_type"] == "positive" else "\U0001f44e"
            reviewer = r.get("reviewer_username") or str(r["reviewer_id"])
            comment_preview = r["comment"][:50]
            ago = _time_ago(r.get("created_at", ""))
            ago_display = f"  ({ago})" if ago else ""
            lines.append(f"  {icon} @{reviewer}: {comment_preview}{ago_display}")

    if references:
        lines.append("")
        lines.append(f"\u2500\u2500\u2500 <b>References ({len(references)})</b> \u2500\u2500\u2500")
        for ref in references:
            ago = _time_ago(ref.get("created_at", ""))
            ago_display = f"  ({ago})" if ago else ""
            submitter = ref.get("submitter_username") or "unknown"
            lines.append(f"  \U0001f517 @{ref['ref_username']}  \u2014 added by @{submitter}{ago_display}")

    if changes or photo_count > 0:
        username_changes = [c for c in (changes or []) if c["change_type"] == "username"]
        name_changes = [c for c in (changes or []) if c["change_type"] == "name"]
        photo_changes = [c for c in (changes or []) if c["change_type"] == "photo"]

        lines.append("")
        lines.append("\u2500\u2500\u2500 <b>Profile History</b> \u2500\u2500\u2500")

        if username_changes:
            lines.append(f"\U0001f4db <b>Username changes:</b> {len(username_changes)}")
            for c in username_changes[:5]:
                old = f"@{c['old_value']}" if c["old_value"] else "<i>none</i>"
                new = f"@{c['new_value']}" if c["new_value"] else "<i>removed</i>"
                ago = _time_ago(c.get("detected_at", ""))
                ago_display = f"  ({ago})" if ago else ""
                lines.append(f"  {old} \u2192 {new}{ago_display}")

        if name_changes:
            lines.append(f"\U0001f464 <b>Name changes:</b> {len(name_changes)}")
            for c in name_changes[:5]:
                old = c["old_value"] or "<i>none</i>"
                new = c["new_value"] or "<i>removed</i>"
                ago = _time_ago(c.get("detected_at", ""))
                ago_display = f"  ({ago})" if ago else ""
                lines.append(f"  {old} \u2192 {new}{ago_display}")

        if photo_count > 0:
            change_note = f" ({len(photo_changes)} change{'s' if len(photo_changes) != 1 else ''})" if photo_changes else ""
            lines.append(f"\U0001f4f8 <b>Profile photos tracked:</b> {photo_count}{change_note}")

    if first_review_date:
        date_display = first_review_date[:10]
        lines.append("")
        lines.append(f"\u2500\u2500\u2500 First reviewed: {date_display} \u2500\u2500\u2500")

    lines.append("\u2501" * 24)
    return "\n".join(lines)


def parse_target(text: str) -> str:
    """Extract a clean username from user input, stripping leading @."""
    cleaned = text.strip().lstrip("@")
    return cleaned


async def check_cooldown(reviewer_id: int, target_id: int, hours: int) -> bool:
    """Return True if the reviewer is still within the cooldown period."""
    return await db.has_recent_review(reviewer_id, target_id, hours)
