from __future__ import annotations

import aiosqlite
from datetime import datetime, timedelta, timezone
from typing import Any

from bot.config import DB_PATH, HIGH_RISK_THRESHOLD

_db: aiosqlite.Connection | None = None


async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is None:
        _db = await aiosqlite.connect(DB_PATH)
        _db.row_factory = aiosqlite.Row
        await _db.execute("PRAGMA journal_mode=WAL")
        await _db.execute("PRAGMA foreign_keys=ON")
    return _db


async def close_db() -> None:
    global _db
    if _db is not None:
        await _db.close()
        _db = None


async def init_db() -> None:
    db = await get_db()
    await db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id     INTEGER PRIMARY KEY,
            username    TEXT,
            first_name  TEXT,
            reputation_score INTEGER DEFAULT 0,
            is_high_risk INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS reviews (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            reviewer_id      INTEGER NOT NULL REFERENCES users(user_id),
            target_id        INTEGER NOT NULL REFERENCES users(user_id),
            review_type      TEXT NOT NULL CHECK(review_type IN ('positive','negative')),
            comment          TEXT NOT NULL,
            proof_file_id    TEXT NOT NULL,
            proof_type       TEXT NOT NULL DEFAULT 'photo',
            status           TEXT NOT NULL DEFAULT 'pending'
                             CHECK(status IN ('pending','approved','rejected')),
            admin_message_id INTEGER,
            created_at       TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(reviewer_id, target_id, id)
        );

        CREATE TABLE IF NOT EXISTS appeals (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            review_id     INTEGER NOT NULL REFERENCES reviews(id),
            appellant_id  INTEGER NOT NULL REFERENCES users(user_id),
            comment       TEXT NOT NULL,
            proof_file_id TEXT,
            status        TEXT NOT NULL DEFAULT 'pending'
                          CHECK(status IN ('pending','upheld','overturned')),
            admin_message_id INTEGER,
            created_at    TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_reviews_target  ON reviews(target_id, status);
        CREATE INDEX IF NOT EXISTS idx_reviews_reviewer ON reviews(reviewer_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_appeals_review   ON appeals(review_id);
        """
    )
    await db.commit()


# ── User helpers ──────────────────────────────────────────────────────

async def upsert_user(user_id: int, username: str | None, first_name: str | None) -> None:
    db = await get_db()
    await db.execute(
        """
        INSERT INTO users (user_id, username, first_name)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username   = excluded.username,
            first_name = excluded.first_name
        """,
        (user_id, username, first_name),
    )
    await db.commit()


async def get_user_by_username(username: str) -> dict[str, Any] | None:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM users WHERE LOWER(username) = LOWER(?)", (username,)
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def get_or_create_user_by_username(username: str) -> dict[str, Any]:
    """Look up a user by username; if not found, create a placeholder record
    with a negative auto-generated ID so reviews can target users who haven't
    interacted with the bot yet."""
    user = await get_user_by_username(username)
    if user:
        return user
    db = await get_db()
    cursor = await db.execute("SELECT MIN(user_id) FROM users")
    row = await cursor.fetchone()
    min_id = row[0] if row[0] is not None else 0
    placeholder_id = min(min_id, 0) - 1
    await db.execute(
        "INSERT INTO users (user_id, username, first_name) VALUES (?, ?, ?)",
        (placeholder_id, username, None),
    )
    await db.commit()
    return {"user_id": placeholder_id, "username": username, "first_name": None,
            "reputation_score": 0, "is_high_risk": 0}


async def get_user_by_id(user_id: int) -> dict[str, Any] | None:
    db = await get_db()
    cursor = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = await cursor.fetchone()
    return dict(row) if row else None


# ── Review helpers ────────────────────────────────────────────────────

async def create_review(
    reviewer_id: int,
    target_id: int,
    review_type: str,
    comment: str,
    proof_file_id: str,
    proof_type: str = "photo",
) -> int:
    db = await get_db()
    cursor = await db.execute(
        """
        INSERT INTO reviews (reviewer_id, target_id, review_type, comment, proof_file_id, proof_type)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (reviewer_id, target_id, review_type, comment, proof_file_id, proof_type),
    )
    await db.commit()
    return cursor.lastrowid  # type: ignore[return-value]


async def get_review(review_id: int) -> dict[str, Any] | None:
    db = await get_db()
    cursor = await db.execute("SELECT * FROM reviews WHERE id = ?", (review_id,))
    row = await cursor.fetchone()
    return dict(row) if row else None


async def set_review_admin_message(review_id: int, admin_message_id: int) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE reviews SET admin_message_id = ? WHERE id = ?",
        (admin_message_id, review_id),
    )
    await db.commit()


async def update_review_status(review_id: int, status: str) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE reviews SET status = ? WHERE id = ?", (status, review_id)
    )
    await db.commit()


async def get_approved_reviews_for_target(target_id: int) -> list[dict[str, Any]]:
    db = await get_db()
    cursor = await db.execute(
        """
        SELECT r.*, u.username AS reviewer_username, u.first_name AS reviewer_first_name
        FROM reviews r
        JOIN users u ON u.user_id = r.reviewer_id
        WHERE r.target_id = ? AND r.status = 'approved'
        ORDER BY r.created_at DESC
        """,
        (target_id,),
    )
    return [dict(row) for row in await cursor.fetchall()]


async def count_approved_reviews(target_id: int) -> tuple[int, int]:
    """Return (positive_count, negative_count) for approved reviews."""
    db = await get_db()
    cursor = await db.execute(
        """
        SELECT
            COALESCE(SUM(CASE WHEN review_type='positive' THEN 1 ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN review_type='negative' THEN 1 ELSE 0 END), 0)
        FROM reviews
        WHERE target_id = ? AND status = 'approved'
        """,
        (target_id,),
    )
    row = await cursor.fetchone()
    return (row[0], row[1])


async def has_recent_review(reviewer_id: int, target_id: int, hours: int) -> bool:
    db = await get_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    cursor = await db.execute(
        """
        SELECT 1 FROM reviews
        WHERE reviewer_id = ? AND target_id = ? AND created_at >= ?
        LIMIT 1
        """,
        (reviewer_id, target_id, cutoff),
    )
    return await cursor.fetchone() is not None


async def recalculate_reputation(target_id: int) -> None:
    pos, neg = await count_approved_reviews(target_id)
    score = pos - neg
    is_high_risk = 1 if neg >= HIGH_RISK_THRESHOLD else 0
    db = await get_db()
    await db.execute(
        "UPDATE users SET reputation_score = ?, is_high_risk = ? WHERE user_id = ?",
        (score, is_high_risk, target_id),
    )
    await db.commit()


# ── Appeal helpers ────────────────────────────────────────────────────

async def get_negative_reviews_for_user(target_id: int) -> list[dict[str, Any]]:
    """Return approved negative reviews targeting this user (for appeals)."""
    db = await get_db()
    cursor = await db.execute(
        """
        SELECT r.*, u.username AS reviewer_username
        FROM reviews r
        JOIN users u ON u.user_id = r.reviewer_id
        WHERE r.target_id = ? AND r.status = 'approved' AND r.review_type = 'negative'
        ORDER BY r.created_at DESC
        """,
        (target_id,),
    )
    return [dict(row) for row in await cursor.fetchall()]


async def has_pending_appeal(review_id: int) -> bool:
    db = await get_db()
    cursor = await db.execute(
        "SELECT 1 FROM appeals WHERE review_id = ? AND status = 'pending' LIMIT 1",
        (review_id,),
    )
    return await cursor.fetchone() is not None


async def create_appeal(
    review_id: int, appellant_id: int, comment: str, proof_file_id: str | None
) -> int:
    db = await get_db()
    cursor = await db.execute(
        """
        INSERT INTO appeals (review_id, appellant_id, comment, proof_file_id)
        VALUES (?, ?, ?, ?)
        """,
        (review_id, appellant_id, comment, proof_file_id),
    )
    await db.commit()
    return cursor.lastrowid  # type: ignore[return-value]


async def get_appeal(appeal_id: int) -> dict[str, Any] | None:
    db = await get_db()
    cursor = await db.execute("SELECT * FROM appeals WHERE id = ?", (appeal_id,))
    row = await cursor.fetchone()
    return dict(row) if row else None


async def set_appeal_admin_message(appeal_id: int, admin_message_id: int) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE appeals SET admin_message_id = ? WHERE id = ?",
        (admin_message_id, appeal_id),
    )
    await db.commit()


async def update_appeal_status(appeal_id: int, status: str) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE appeals SET status = ? WHERE id = ?", (status, appeal_id)
    )
    await db.commit()


# ── Web panel queries ─────────────────────────────────────────────────

async def get_pending_reviews() -> list[dict[str, Any]]:
    db = await get_db()
    cursor = await db.execute(
        """
        SELECT r.*,
               rev.username AS reviewer_username, rev.first_name AS reviewer_first_name,
               tgt.username AS target_username,   tgt.first_name AS target_first_name
        FROM reviews r
        JOIN users rev ON rev.user_id = r.reviewer_id
        JOIN users tgt ON tgt.user_id = r.target_id
        WHERE r.status = 'pending'
        ORDER BY r.created_at DESC
        """
    )
    return [dict(row) for row in await cursor.fetchall()]


async def get_all_reviews(status_filter: str | None = None) -> list[dict[str, Any]]:
    db = await get_db()
    if status_filter:
        cursor = await db.execute(
            """
            SELECT r.*,
                   rev.username AS reviewer_username, rev.first_name AS reviewer_first_name,
                   tgt.username AS target_username,   tgt.first_name AS target_first_name
            FROM reviews r
            JOIN users rev ON rev.user_id = r.reviewer_id
            JOIN users tgt ON tgt.user_id = r.target_id
            WHERE r.status = ?
            ORDER BY r.created_at DESC
            """,
            (status_filter,),
        )
    else:
        cursor = await db.execute(
            """
            SELECT r.*,
                   rev.username AS reviewer_username, rev.first_name AS reviewer_first_name,
                   tgt.username AS target_username,   tgt.first_name AS target_first_name
            FROM reviews r
            JOIN users rev ON rev.user_id = r.reviewer_id
            JOIN users tgt ON tgt.user_id = r.target_id
            ORDER BY r.created_at DESC
            """
        )
    return [dict(row) for row in await cursor.fetchall()]


async def get_pending_appeals() -> list[dict[str, Any]]:
    db = await get_db()
    cursor = await db.execute(
        """
        SELECT a.*,
               ap.username AS appellant_username, ap.first_name AS appellant_first_name,
               r.review_type, r.comment AS review_comment, r.proof_file_id AS review_proof_file_id,
               r.proof_type AS review_proof_type, r.reviewer_id,
               rev.username AS reviewer_username,
               tgt.username AS target_username
        FROM appeals a
        JOIN users ap  ON ap.user_id  = a.appellant_id
        JOIN reviews r ON r.id        = a.review_id
        JOIN users rev ON rev.user_id = r.reviewer_id
        JOIN users tgt ON tgt.user_id = r.target_id
        WHERE a.status = 'pending'
        ORDER BY a.created_at DESC
        """
    )
    return [dict(row) for row in await cursor.fetchall()]


async def get_all_appeals(status_filter: str | None = None) -> list[dict[str, Any]]:
    db = await get_db()
    base = """
        SELECT a.*,
               ap.username AS appellant_username, ap.first_name AS appellant_first_name,
               r.review_type, r.comment AS review_comment, r.proof_file_id AS review_proof_file_id,
               r.proof_type AS review_proof_type, r.reviewer_id,
               rev.username AS reviewer_username,
               tgt.username AS target_username
        FROM appeals a
        JOIN users ap  ON ap.user_id  = a.appellant_id
        JOIN reviews r ON r.id        = a.review_id
        JOIN users rev ON rev.user_id = r.reviewer_id
        JOIN users tgt ON tgt.user_id = r.target_id
    """
    if status_filter:
        cursor = await db.execute(
            base + " WHERE a.status = ? ORDER BY a.created_at DESC",
            (status_filter,),
        )
    else:
        cursor = await db.execute(base + " ORDER BY a.created_at DESC")
    return [dict(row) for row in await cursor.fetchall()]


async def count_pending() -> dict[str, int]:
    db = await get_db()
    cursor = await db.execute("SELECT COUNT(*) FROM reviews WHERE status = 'pending'")
    row = await cursor.fetchone()
    pending_reviews = row[0]
    cursor = await db.execute("SELECT COUNT(*) FROM appeals WHERE status = 'pending'")
    row = await cursor.fetchone()
    pending_appeals = row[0]
    return {"reviews": pending_reviews, "appeals": pending_appeals}
