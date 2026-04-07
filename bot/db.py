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

        CREATE TABLE IF NOT EXISTS review_proofs (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            review_id  INTEGER NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
            file_id    TEXT NOT NULL,
            proof_type TEXT NOT NULL DEFAULT 'photo'
        );

        CREATE TABLE IF NOT EXISTS refs (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            submitter_id   INTEGER NOT NULL REFERENCES users(user_id),
            target_id      INTEGER NOT NULL REFERENCES users(user_id),
            ref_username   TEXT NOT NULL,
            status         TEXT NOT NULL DEFAULT 'pending'
                           CHECK(status IN ('pending','approved','rejected')),
            created_at     TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS ref_proofs (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            ref_id     INTEGER NOT NULL REFERENCES refs(id) ON DELETE CASCADE,
            file_id    TEXT NOT NULL,
            proof_type TEXT NOT NULL DEFAULT 'photo'
        );

        CREATE TABLE IF NOT EXISTS user_changes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            change_type TEXT NOT NULL,
            old_value   TEXT,
            new_value   TEXT,
            detected_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS user_photos (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id        INTEGER NOT NULL,
            file_id        TEXT NOT NULL,
            file_unique_id TEXT NOT NULL,
            detected_at    TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(user_id, file_unique_id)
        );

        CREATE INDEX IF NOT EXISTS idx_user_changes_user ON user_changes(user_id, detected_at);
        CREATE INDEX IF NOT EXISTS idx_user_photos_user ON user_photos(user_id);
        CREATE INDEX IF NOT EXISTS idx_reviews_target  ON reviews(target_id, status);
        CREATE INDEX IF NOT EXISTS idx_reviews_reviewer ON reviews(reviewer_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_appeals_review   ON appeals(review_id);
        CREATE INDEX IF NOT EXISTS idx_review_proofs_review ON review_proofs(review_id);
        CREATE INDEX IF NOT EXISTS idx_refs_target ON refs(target_id, status);
        CREATE INDEX IF NOT EXISTS idx_ref_proofs_ref ON ref_proofs(ref_id);
        """
    )

    # Migrate legacy single-proof rows into review_proofs if not already done
    cursor = await db.execute(
        """
        SELECT r.id, r.proof_file_id, r.proof_type
        FROM reviews r
        WHERE r.proof_file_id IS NOT NULL AND r.proof_file_id != ''
          AND NOT EXISTS (SELECT 1 FROM review_proofs rp WHERE rp.review_id = r.id)
        """
    )
    legacy_rows = await cursor.fetchall()
    if legacy_rows:
        await db.executemany(
            "INSERT INTO review_proofs (review_id, file_id, proof_type) VALUES (?, ?, ?)",
            [(row[0], row[1], row[2]) for row in legacy_rows],
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


# ── Profile tracking helpers ──────────────────────────────────────────

async def log_user_change(
    user_id: int, change_type: str, old_value: str | None, new_value: str | None,
) -> None:
    conn = await get_db()
    await conn.execute(
        "INSERT INTO user_changes (user_id, change_type, old_value, new_value) VALUES (?, ?, ?, ?)",
        (user_id, change_type, old_value, new_value),
    )
    await conn.commit()


async def get_user_changes(user_id: int, limit: int = 20) -> list[dict[str, Any]]:
    conn = await get_db()
    cursor = await conn.execute(
        "SELECT * FROM user_changes WHERE user_id = ? ORDER BY detected_at DESC LIMIT ?",
        (user_id, limit),
    )
    return [dict(row) for row in await cursor.fetchall()]


async def track_user_photo(user_id: int, file_id: str, file_unique_id: str) -> bool:
    """Store a profile photo. Returns True if this was a previously unseen photo."""
    conn = await get_db()
    try:
        await conn.execute(
            "INSERT INTO user_photos (user_id, file_id, file_unique_id) VALUES (?, ?, ?)",
            (user_id, file_id, file_unique_id),
        )
        await conn.commit()
        return True
    except Exception:
        return False


async def get_user_photos(user_id: int) -> list[dict[str, Any]]:
    conn = await get_db()
    cursor = await conn.execute(
        "SELECT * FROM user_photos WHERE user_id = ? ORDER BY detected_at DESC",
        (user_id,),
    )
    return [dict(row) for row in await cursor.fetchall()]


async def count_user_photos(user_id: int) -> int:
    conn = await get_db()
    cursor = await conn.execute(
        "SELECT COUNT(*) FROM user_photos WHERE user_id = ?", (user_id,),
    )
    row = await cursor.fetchone()
    return row[0]


# ── Review helpers ────────────────────────────────────────────────────

async def create_review(
    reviewer_id: int,
    target_id: int,
    review_type: str,
    comment: str,
    proof_file_id: str,
    proof_type: str = "photo",
    extra_proofs: list[dict] | None = None,
) -> int:
    """Create a review with one or more proofs.

    ``proof_file_id`` / ``proof_type`` are the primary proof (kept in the
    reviews row for backward compat).  ``extra_proofs`` is an optional list
    of ``{"file_id": ..., "proof_type": ...}`` dicts for additional media.
    All proofs (including the primary) are also stored in ``review_proofs``.
    """
    conn = await get_db()
    cursor = await conn.execute(
        """
        INSERT INTO reviews (reviewer_id, target_id, review_type, comment, proof_file_id, proof_type)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (reviewer_id, target_id, review_type, comment, proof_file_id, proof_type),
    )
    review_id: int = cursor.lastrowid  # type: ignore[assignment]

    all_proofs = [{"file_id": proof_file_id, "proof_type": proof_type}]
    if extra_proofs:
        all_proofs.extend(extra_proofs)

    await conn.executemany(
        "INSERT INTO review_proofs (review_id, file_id, proof_type) VALUES (?, ?, ?)",
        [(review_id, p["file_id"], p["proof_type"]) for p in all_proofs],
    )

    await conn.commit()
    return review_id


async def get_review(review_id: int) -> dict[str, Any] | None:
    db = await get_db()
    cursor = await db.execute("SELECT * FROM reviews WHERE id = ?", (review_id,))
    row = await cursor.fetchone()
    return dict(row) if row else None


async def get_review_proofs(review_id: int) -> list[dict[str, Any]]:
    """Return all proof records for a review from the review_proofs table."""
    conn = await get_db()
    cursor = await conn.execute(
        "SELECT * FROM review_proofs WHERE review_id = ? ORDER BY id",
        (review_id,),
    )
    return [dict(row) for row in await cursor.fetchall()]


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


async def get_first_review_date(target_id: int) -> str | None:
    db = await get_db()
    cursor = await db.execute(
        """
        SELECT MIN(created_at) FROM reviews
        WHERE target_id = ? AND status = 'approved'
        """,
        (target_id,),
    )
    row = await cursor.fetchone()
    return row[0] if row and row[0] else None


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


# ── Reference helpers ─────────────────────────────────────────────────

async def create_reference(
    submitter_id: int,
    target_id: int,
    ref_username: str,
    proofs: list[dict],
) -> int:
    conn = await get_db()
    cursor = await conn.execute(
        "INSERT INTO refs (submitter_id, target_id, ref_username) VALUES (?, ?, ?)",
        (submitter_id, target_id, ref_username),
    )
    ref_id: int = cursor.lastrowid  # type: ignore[assignment]

    if proofs:
        await conn.executemany(
            "INSERT INTO ref_proofs (ref_id, file_id, proof_type) VALUES (?, ?, ?)",
            [(ref_id, p["file_id"], p["proof_type"]) for p in proofs],
        )

    await conn.commit()
    return ref_id


async def get_reference(ref_id: int) -> dict[str, Any] | None:
    conn = await get_db()
    cursor = await conn.execute("SELECT * FROM refs WHERE id = ?", (ref_id,))
    row = await cursor.fetchone()
    return dict(row) if row else None


async def get_ref_proofs(ref_id: int) -> list[dict[str, Any]]:
    conn = await get_db()
    cursor = await conn.execute(
        "SELECT * FROM ref_proofs WHERE ref_id = ? ORDER BY id", (ref_id,),
    )
    return [dict(row) for row in await cursor.fetchall()]


async def update_reference_status(ref_id: int, status: str) -> None:
    conn = await get_db()
    await conn.execute("UPDATE refs SET status = ? WHERE id = ?", (status, ref_id))
    await conn.commit()


async def get_approved_refs_for_target(target_id: int) -> list[dict[str, Any]]:
    conn = await get_db()
    cursor = await conn.execute(
        """
        SELECT r.*, u.username AS submitter_username
        FROM refs r
        JOIN users u ON u.user_id = r.submitter_id
        WHERE r.target_id = ? AND r.status = 'approved'
        ORDER BY r.created_at DESC
        """,
        (target_id,),
    )
    return [dict(row) for row in await cursor.fetchall()]


async def get_all_refs(status_filter: str | None = None) -> list[dict[str, Any]]:
    conn = await get_db()
    base = """
        SELECT r.*,
               sub.username AS submitter_username, sub.first_name AS submitter_first_name,
               tgt.username AS target_username, tgt.first_name AS target_first_name
        FROM refs r
        JOIN users sub ON sub.user_id = r.submitter_id
        JOIN users tgt ON tgt.user_id = r.target_id
    """
    if status_filter:
        cursor = await conn.execute(
            base + " WHERE r.status = ? ORDER BY r.created_at DESC",
            (status_filter,),
        )
    else:
        cursor = await conn.execute(base + " ORDER BY r.created_at DESC")
    return [dict(row) for row in await cursor.fetchall()]


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
    cursor = await db.execute("SELECT COUNT(*) FROM refs WHERE status = 'pending'")
    row = await cursor.fetchone()
    pending_refs = row[0]
    return {"reviews": pending_reviews, "appeals": pending_appeals, "refs": pending_refs}
