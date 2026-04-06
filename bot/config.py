import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

BOT_TOKEN: str = os.environ["BOT_TOKEN"]
HIGH_RISK_THRESHOLD: int = int(os.getenv("HIGH_RISK_THRESHOLD", "3"))
REVIEW_COOLDOWN_HOURS: int = int(os.getenv("REVIEW_COOLDOWN_HOURS", "24"))

DB_PATH: str = os.getenv("DB_PATH", str(Path(__file__).resolve().parent.parent / "reviews.db"))

ADMIN_USER_IDS: list[int] = [
    int(uid.strip())
    for uid in os.getenv("ADMIN_USER_IDS", "").split(",")
    if uid.strip() and uid.strip().isdigit()
]

WEB_PORT: int = int(os.getenv("WEB_PORT", "8080"))
ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "admin")
