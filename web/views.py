from __future__ import annotations

import aiohttp_jinja2
from aiohttp import web

from bot import db
from web.auth import set_admin_cookie, clear_admin_cookie, check_password


async def login_page(request: web.Request) -> web.Response:
    error = request.query.get("error", "")
    return aiohttp_jinja2.render_template("login.html", request, {"error": error})


async def login_submit(request: web.Request) -> web.Response:
    data = await request.post()
    password = data.get("password", "")

    if not check_password(password):
        raise web.HTTPFound("/login?error=Wrong+password")

    resp = web.HTTPFound("/")
    set_admin_cookie(resp)
    raise resp


async def logout(request: web.Request) -> web.Response:
    resp = web.HTTPFound("/login")
    clear_admin_cookie(resp)
    raise resp


@aiohttp_jinja2.template("dashboard.html")
async def dashboard(request: web.Request) -> dict:
    counts = await db.count_pending()
    return {"admin": request["admin"], "counts": counts}


@aiohttp_jinja2.template("reviews.html")
async def reviews_list(request: web.Request) -> dict:
    status_filter = request.query.get("status", "pending")
    if status_filter == "all":
        status_filter = None
    reviews = await db.get_all_reviews(status_filter)

    for r in reviews:
        proofs = await db.get_review_proofs(r["id"])
        r["proofs"] = proofs if proofs else [{"file_id": r["proof_file_id"], "proof_type": r.get("proof_type", "photo")}]

    return {
        "admin": request["admin"],
        "reviews": reviews,
        "current_filter": request.query.get("status", "pending"),
    }


async def approve_review(request: web.Request) -> web.Response:
    review_id = int(request.match_info["id"])
    review = await db.get_review(review_id)
    if not review or review["status"] != "pending":
        raise web.HTTPNotFound(text="Review not found or already processed.")

    await db.update_review_status(review_id, "approved")
    await db.recalculate_reputation(review["target_id"])

    bot = request.app["bot"]
    try:
        type_label = "vouch" if review["review_type"] == "positive" else "negative review"
        target = await db.get_user_by_id(review["target_id"])
        target_display = f"@{target['username']}" if target and target["username"] else f"ID {review['target_id']}"
        await bot.send_message(
            review["reviewer_id"],
            f"Your {type_label} for {target_display} (Review #{review_id}) has been <b>approved</b>.",
            parse_mode="HTML",
        )
    except Exception:
        pass

    raise web.HTTPFound("/reviews")


async def reject_review(request: web.Request) -> web.Response:
    review_id = int(request.match_info["id"])
    review = await db.get_review(review_id)
    if not review or review["status"] != "pending":
        raise web.HTTPNotFound(text="Review not found or already processed.")

    await db.update_review_status(review_id, "rejected")

    bot = request.app["bot"]
    try:
        type_label = "vouch" if review["review_type"] == "positive" else "negative review"
        target = await db.get_user_by_id(review["target_id"])
        target_display = f"@{target['username']}" if target and target["username"] else f"ID {review['target_id']}"
        await bot.send_message(
            review["reviewer_id"],
            f"Your {type_label} for {target_display} (Review #{review_id}) has been <b>rejected</b>.",
            parse_mode="HTML",
        )
    except Exception:
        pass

    raise web.HTTPFound("/reviews")


@aiohttp_jinja2.template("appeals.html")
async def appeals_list(request: web.Request) -> dict:
    status_filter = request.query.get("status", "pending")
    if status_filter == "all":
        status_filter = None
    appeals = await db.get_all_appeals(status_filter)

    for a in appeals:
        proofs = await db.get_review_proofs(a["review_id"])
        a["review_proofs"] = proofs if proofs else [{"file_id": a["review_proof_file_id"], "proof_type": a.get("review_proof_type", "photo")}]

    return {
        "admin": request["admin"],
        "appeals": appeals,
        "current_filter": request.query.get("status", "pending"),
    }


async def uphold_appeal(request: web.Request) -> web.Response:
    appeal_id = int(request.match_info["id"])
    appeal = await db.get_appeal(appeal_id)
    if not appeal or appeal["status"] != "pending":
        raise web.HTTPNotFound(text="Appeal not found or already processed.")

    await db.update_appeal_status(appeal_id, "upheld")

    bot = request.app["bot"]
    try:
        await bot.send_message(
            appeal["appellant_id"],
            f"Your appeal for Review #{appeal['review_id']} has been <b>upheld</b>. "
            "The original review remains.",
            parse_mode="HTML",
        )
    except Exception:
        pass

    raise web.HTTPFound("/appeals")


async def overturn_appeal(request: web.Request) -> web.Response:
    appeal_id = int(request.match_info["id"])
    appeal = await db.get_appeal(appeal_id)
    if not appeal or appeal["status"] != "pending":
        raise web.HTTPNotFound(text="Appeal not found or already processed.")

    await db.update_appeal_status(appeal_id, "overturned")

    review = await db.get_review(appeal["review_id"])
    if review:
        await db.update_review_status(review["id"], "rejected")
        await db.recalculate_reputation(review["target_id"])

    bot = request.app["bot"]
    try:
        await bot.send_message(
            appeal["appellant_id"],
            f"Your appeal for Review #{appeal['review_id']} has been <b>overturned</b>. "
            "The negative review has been removed.",
            parse_mode="HTML",
        )
    except Exception:
        pass

    raise web.HTTPFound("/appeals")


# ── Reference moderation ─────────────────────────────────────────────

@aiohttp_jinja2.template("references.html")
async def refs_list(request: web.Request) -> dict:
    status_filter = request.query.get("status", "pending")
    if status_filter == "all":
        status_filter = None
    refs = await db.get_all_refs(status_filter)

    for r in refs:
        r["proofs"] = await db.get_ref_proofs(r["id"])

    return {
        "admin": request["admin"],
        "refs": refs,
        "current_filter": request.query.get("status", "pending"),
    }


async def approve_ref(request: web.Request) -> web.Response:
    ref_id = int(request.match_info["id"])
    ref = await db.get_reference(ref_id)
    if not ref or ref["status"] != "pending":
        raise web.HTTPNotFound(text="Reference not found or already processed.")

    await db.update_reference_status(ref_id, "approved")

    bot = request.app["bot"]
    try:
        target = await db.get_user_by_id(ref["target_id"])
        target_display = f"@{target['username']}" if target and target["username"] else f"ID {ref['target_id']}"
        await bot.send_message(
            ref["submitter_id"],
            f"\u2705 Your reference <b>@{ref['ref_username']}</b> for {target_display} "
            f"(Ref #{ref_id}) has been <b>approved</b>.",
            parse_mode="HTML",
        )
    except Exception:
        pass

    raise web.HTTPFound("/references")


async def reject_ref(request: web.Request) -> web.Response:
    ref_id = int(request.match_info["id"])
    ref = await db.get_reference(ref_id)
    if not ref or ref["status"] != "pending":
        raise web.HTTPNotFound(text="Reference not found or already processed.")

    await db.update_reference_status(ref_id, "rejected")

    bot = request.app["bot"]
    try:
        target = await db.get_user_by_id(ref["target_id"])
        target_display = f"@{target['username']}" if target and target["username"] else f"ID {ref['target_id']}"
        await bot.send_message(
            ref["submitter_id"],
            f"\u274c Your reference <b>@{ref['ref_username']}</b> for {target_display} "
            f"(Ref #{ref_id}) has been <b>rejected</b>.",
            parse_mode="HTML",
        )
    except Exception:
        pass

    raise web.HTTPFound("/references")
