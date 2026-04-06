# Telegram Social Proof Reviews Bot

A Telegram bot for collecting and verifying user vouches and negative reviews with mandatory screenshot/video proof and a web-based admin panel for moderation.

## Features

- **Reputation lookup** -- `/check @username` shows a user's score, vouches, negatives, and HIGH RISK flag
- **Review submission** -- guided FSM flow: target, vouch/negative, comment, mandatory screenshot or video
- **Web admin panel** -- modern dashboard at `http://localhost:8080` with Telegram Login authentication
- **Appeal process** -- negatively reviewed users can appeal; admins can uphold or overturn via the web panel
- **Anti-spam** -- 24-hour cooldown per reviewer-target pair
- **Scammer tagging** -- users with 3+ verified negatives are auto-tagged as HIGH RISK
- **Username tracking** -- stores numerical user IDs so name changes don't hide history

## Setup

### 1. Create the bot via BotFather

1. Open Telegram and search for **@BotFather**.
2. Send `/newbot` and follow the prompts to choose a name and username.
3. Copy the **HTTP API token** you receive.

### 2. Get your Telegram user ID

You need your numerical Telegram user ID to be an admin. Send `/start` to **@userinfobot** on Telegram to find it.

### 3. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and fill in:

```
BOT_TOKEN=123456:ABC-DEF...
ADMIN_USER_IDS=your_telegram_user_id
WEB_PORT=8080
HIGH_RISK_THRESHOLD=3
REVIEW_COOLDOWN_HOURS=24
```

Multiple admin IDs can be comma-separated: `ADMIN_USER_IDS=111,222,333`

### 4. Install dependencies

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Linux / macOS
source venv/bin/activate

pip install -r requirements.txt
```

### 5. Run

```bash
python -m bot.main
```

This starts both:
- The **Telegram bot** (polling for updates)
- The **web admin panel** on `http://localhost:8080`

The SQLite database (`reviews.db`) is created automatically on first run.

### 6. Log into the admin panel

1. Open `http://localhost:8080` in your browser.
2. Click "Log in with Telegram."
3. Authorize with your Telegram account.
4. You'll see the dashboard with pending reviews and appeals.

## Bot Commands

| Command | Description |
|---|---|
| `/start` | Welcome message and help |
| `/help` | Show available commands |
| `/check @username` | Look up a user's reputation |
| `/review` | Submit a vouch or negative review |
| `/appeal` | Appeal a negative review against you |

## Web Admin Panel

| Page | Description |
|---|---|
| `/` | Dashboard with pending counts |
| `/reviews` | List reviews, filter by status, approve or reject |
| `/appeals` | List appeals, filter by status, uphold or overturn |

Proof media (screenshots, videos) are viewable directly in the browser via on-demand proxy from Telegram servers.

## Project Structure

```
bot/
  main.py           Entry point (bot + web server)
  config.py         Environment variables
  db.py             SQLite database layer
  states.py         FSM state groups
  keyboards.py      Inline and reply keyboards
  utils.py          Formatting and helpers
  handlers/
    start.py        /start, /help
    check.py        /check with proof viewing
    review.py       /review FSM
    appeal.py       /appeal FSM
web/
  app.py            aiohttp app factory
  auth.py           Telegram Login verification and sessions
  views.py          Dashboard, reviews, appeals, approve/reject
  media.py          Proof media proxy from Telegram
  templates/
    base.html       Layout
    login.html      Telegram Login Widget
    dashboard.html  Pending counts
    reviews.html    Reviews table with actions
    appeals.html    Appeals table with actions
```
