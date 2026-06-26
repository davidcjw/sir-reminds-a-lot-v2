# Sir Reminds A Lot

![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![Docker](https://img.shields.io/badge/docker-supported-blue)

A personal Telegram bot for tracking credit card spending and sending payment due-date reminders.

## Table of Contents

- [Requirements](#requirements)
- [Setup](#setup-macos-linuxubuntudebian)
- [Optional: Daily Reminders](#optional-daily-reminders)
- [Commands](#commands)
- [Hosting](#hosting)
- [Data](#data)
- [Development](#development)
- [Contributing](#contributing)
- [Code of Conduct](#code-of-conduct)
- [License](#license)

- 📓 Logs spend entries to a local SQLite database
- 🔖 Summarises spend per card by billing period
- 🔔 Sends daily reminders for upcoming due dates
- 💳 Type any merchant name in the chat to get the right card to use
- 🤖 Fully configured via bot commands — no files to edit
- 📁 Export your data to csv for your own book-keeping

## Requirements

- Docker (recommended), or Python 3.11+
- A Telegram bot token from [@BotFather](https://t.me/BotFather)

## Setup (MacOS, Linux/Ubuntu/Debian)

### AI-assisted setup (*recommended*)

Paste the prompt below into any AI agent (Claude, ChatGPT, Codex, etc.) and it will walk you through the entire installation interactively — including creating the Telegram bot, installing dependencies, and starting the bot.

````
You are going to help me set up a self-hosted Telegram spend-tracking bot called
"Sir Reminds A Lot" on my machine. Guide me through every step interactively,
running commands on my behalf where possible and asking me for input when you need
something only I can provide (like a token or a choice).

Follow these steps in order:

---

STEP 1 — Detect environment
- Detect my operating system (macOS or Linux/Ubuntu/Debian) and confirm it with me.
- Check whether Docker is installed by running `docker --version`.
- Check whether Python 3.11+ is installed by running `python3 --version`.
- Tell me what you found. We will use Docker if it is available; otherwise Python.

---

STEP 2 — Install missing dependencies

If Docker is NOT installed:
  macOS:
    - Install Homebrew if missing: /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    - Install Docker Desktop: brew install --cask docker
    - Tell me to open Docker Desktop and wait until it is running, then confirm with me before continuing.
  Linux:
    - Run: sudo apt-get update && sudo apt-get install -y docker.io docker-compose-plugin
    - Run: sudo systemctl enable --now docker
    - Add me to the docker group: sudo usermod -aG docker $USER
    - Tell me to log out and back in (or run `newgrp docker`) and confirm before continuing.

If Python 3.11+ is NOT installed and we are falling back to Python:
  macOS:  brew install python@3.11
  Linux:  sudo apt-get install -y python3.11 python3.11-venv python3-pip

Also ensure git is installed:
  macOS:  brew install git   (if missing)
  Linux:  sudo apt-get install -y git   (if missing)

---

STEP 3 — Create a Telegram bot

Tell me: "We need to create a Telegram bot to get your token. Open Telegram on your
phone or desktop and follow these steps:
  1. Search for @BotFather and start a chat.
  2. Send the message: /newbot
  3. Choose a display name for your bot (e.g. My Spend Tracker).
  4. Choose a username ending in 'bot' (e.g. myspend_bot).
  5. BotFather will reply with a token that looks like: 123456789:ABCdefGHI...
  6. Paste that token here."

Wait for me to paste the token. Validate that it matches the pattern
`[0-9]+:[A-Za-z0-9_-]{35,}`. If it does not match, ask me to check and try again.
Store the token as BOT_TOKEN for use in Step 5.

---

STEP 4 — Clone the repository

Run:
  git clone https://github.com/davidcjw/sir-reminds-a-lot-v2.git
  cd sir-reminds-a-lot-v2

---

STEP 5 — Configure environment

Run:
  cp .env.example .env

Write BOT_TOKEN into the .env file by replacing the TELEGRAM_BOT_TOKEN line:
  sed -i'' -e "s|TELEGRAM_BOT_TOKEN=.*|TELEGRAM_BOT_TOKEN=${BOT_TOKEN}|" .env
  (On macOS use: sed -i '' ...)

Ask me: "Do you want daily payment reminders? (yes/no)"
If yes:
  Ask for: reminder time (default 09:00), timezone (default Asia/Singapore),
           days before due date to remind (default 3).
  Tell me: "Start the bot, send /chatid to it, then paste the chat ID here."
  Wait for the chat ID, then write all reminder values into .env.

---

STEP 5.5 — Interactive setup: seed cards, categories, merchants, and rules

Walk me through each section below in order. For each, accept either a typed
answer or a dropped .csv / .md / .txt file (parse the file the same way).
Insert everything directly into the database using db.py (the database path
comes from DATABASE_PATH in .env, default ./data/bot.db):

  python3 - <<'EOF'
  from pathlib import Path
  import db
  db.init(Path("./data/bot.db"))
  # ... insert calls here ...
  EOF

After ALL sections are done, print one combined summary of everything added.
If anything is ambiguous, show what you parsed and ask me to confirm before
inserting. Never insert the same value twice.

── CATEGORIES ──────────────────────────────────────────────────────────────
Ask: "What spending categories do you want? List them separated by commas,
or one per line. Examples: Groceries, Dining, Transport, Shopping, Travel."
Accept free text. Split on commas or newlines, trim whitespace, call
db.add_category() for each.

── CARDS ────────────────────────────────────────────────────────────────────
Ask: "Add your credit/debit cards. For each card provide:
  name, due day (e.g. 15, last), billing cycle start day (1 = calendar month)
Separate fields with commas, one card per line. Example:
  DBS Visa, 15, 1
  UOB One, last, 13
Leave due day or cycle blank to skip."
Parse each line and call db.add_card(name, due_day, cycle_start).

── MERCHANT → CATEGORY MAPPINGS ────────────────────────────────────────────
Ask: "Do you want to load the default Singapore merchant list? It maps ~200
common merchants (NTUC, Grab, Starbucks, Shopee, etc.) to categories like
Groceries, Dining, Transport, Online Shopping, and more. (yes/no)"
If yes: read merchant_categories.md from the repo root and call
  db.add_merchant_alias(merchant, category) for every non-header table row.
  Also call db.add_category(category) for any category not yet in the DB.
If no: ask "Enter your own merchant → category mappings, one per line
  (e.g. NTUC → Groceries). Leave blank to skip."
  Parse and insert each.

---

STEP 6 — Start the bot

If using Docker:
  docker compose up -d
  Verify: docker compose ps  (confirm the bot container is running)

If using Python:
  python3 -m venv .venv
  source .venv/bin/activate   (macOS/Linux)
  pip install -r requirements.txt
  nohup python3 bot.py &> bot.log &
  Verify: tail -5 bot.log  (confirm "Bot starting" appears)

---

STEP 7 — Verify and hand off

Tell me to open Telegram and send /start to my bot. Confirm I see the main menu.

Then print this message:
"✅ Your bot is running! Next steps:
  - Your cards, categories, and merchants are configured — send /start to begin.
  - Use /admin anytime to add, edit, or remove cards, categories, merchants, and rules.
  - Send /chatid to get your chat ID if you want to enable reminders later.
  - Send /help anytime to see all available commands.
  - Your data is stored in ./data/bot.db — back it up by copying that file."

If anything fails at any step, show me the error output and suggest a fix before
continuing. Do not skip steps silently.
````

### Manual setup

**1. Clone and configure**

```bash
git clone https://github.com/davidcjw/sir-reminds-a-lot-v2.git && cd sir-reminds-a-lot-v2
cp .env.example .env
```

Open `.env` and set `TELEGRAM_BOT_TOKEN`.

**2. Run**

```bash
docker compose up -d
```

Or without Docker:

```bash
pip install -r requirements.txt
python bot.py
```

**Run as a systemd service (Linux)**

To keep the bot running after logout and have it auto-start on reboot:

```bash
# Create a virtual environment and install dependencies
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Create the service file (replace `/home/youruser/sir-reminds-a-lot-v2` with your actual path and `youruser` with your Linux username):

```bash
sudo nano /etc/systemd/system/sir-reminds-a-lot.service
```

Paste:

```ini
[Unit]
Description=Sir Reminds A Lot Telegram Bot
After=network.target

[Service]
Type=simple
User=youruser
WorkingDirectory=/home/youruser/sir-reminds-a-lot-v2
EnvironmentFile=/home/youruser/sir-reminds-a-lot-v2/.env
ExecStart=/home/youruser/sir-reminds-a-lot-v2/.venv/bin/python bot.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable sir-reminds-a-lot
sudo systemctl start sir-reminds-a-lot
```

Check status and logs:

```bash
sudo systemctl status sir-reminds-a-lot
journalctl -u sir-reminds-a-lot -f
```

If logs show `sqlite3.OperationalError: attempt to write a readonly database`,
make sure the service user owns both the database file and the `data` directory.
SQLite needs directory write access so it can create journal files.

```bash
cd /home/youruser/sir-reminds-a-lot-v2
sudo systemctl stop sir-reminds-a-lot
mkdir -p data
sudo chown -R youruser:youruser data
chmod u+rwX data data/bot.db 2>/dev/null || true
sudo systemctl start sir-reminds-a-lot
```

For systemd, prefer an absolute database path in `.env` so it does not depend on
the process working directory:

```env
DATABASE_PATH=/home/youruser/sir-reminds-a-lot-v2/data/bot.db
```

**3. Configure via the bot**

Send `/admin` to the bot and use the inline menu to set up:

| Section | What to add |
|---------|-------------|
| **Cards** | Card name, due day (e.g. `15th`, `last`), billing cycle start day |
| **Categories** | Spend categories (e.g. Groceries, Transport, Dining) |
| **Merchants** | Merchant → category mappings (e.g. NTUC → Groceries) |
| **Rules** | Category → card recommendation (e.g. Groceries → UOB Ladies) |

## Optional: daily reminders

Get your chat ID by sending `/chatid` to the bot, then add to `.env`:

```
TELEGRAM_REMINDER_CHAT_ID=<your chat id>
TELEGRAM_REMINDER_TIME=09:00
TELEGRAM_REMINDER_TIMEZONE=Asia/Singapore
TELEGRAM_REMINDER_DAYS_BEFORE=3
```

Restart the bot after editing `.env`.

## Commands

Just type any merchant name (e.g. `Starbucks`, `NTUC`, `Grab`) to get the recommended card for that spend. Punctuation is ignored — `McDonald's` and `McDonalds` both work. For merchants mapped to the "Shopping" sentinel, the bot will ask whether the purchase is in-store or online before replying.

| Command | Description |
|---------|-------------|
| `/spend` | Log a spend entry |
| `/spend_summary` | Spend by card for the current billing period |
| `/transactions` | Show your latest 5 transactions |
| `/category_chart` | Pie chart of spend by category this month |
| `/due` | Upcoming card due dates |
| `/reminders` | Check what's due within your reminder window |
| `/delete_last` | Delete the most recent spend entry (with confirmation) |
| `/export` | Download all spend data as a CSV file |
| `/admin` | Manage cards, categories, merchants, and rules |
| `/chatid` | Show this chat's ID |

## Hosting

If you're setting up via AI assisted chat, ensure you install the relevant LLM tool (e.g. Claude).

The bot needs to run continuously to send reminders. Three options, from easiest to most control:

### Fly.io (recommended for most people)

Free tier includes a persistent volume, so your SQLite data survives restarts.

```bash
# Install the CLI: https://fly.io/docs/hands-on/install-flyctl/
fly launch
fly secrets set TELEGRAM_BOT_TOKEN=xxx
fly volumes create bot_data --size 1
fly deploy
```

Cost: free for a single small app with one volume.

### VPS — Hetzner / DigitalOcean / Vultr

A Hetzner CX22 (~€4/month) is more than enough. SSH in and run:

```bash
apt install docker.io docker-compose-plugin
git clone https://github.com/davidcjw/sir-reminds-a-lot-v2.git && cd sir-reminds-a-lot-v2
cp .env.example .env && nano .env
docker compose up -d
```

Data lives on the server disk. Best option if you want full control and low cost long-term.

### Raspberry Pi (free, runs at home)

Same Docker setup as VPS. No monthly cost and data never leaves your machine.

```bash
# On the Pi:
git clone https://github.com/davidcjw/sir-reminds-a-lot-v2.git && cd sir-reminds-a-lot-v2
cp .env.example .env && nano .env
docker compose up -d
```

Requires Docker installed on the Pi (`apt install docker.io docker-compose-plugin`). Bot availability depends on your home internet uptime.

---

| Option | Cost | Difficulty | Data |
|--------|------|------------|------|
| Fly.io | Free | Low | Persistent volume |
| VPS (Hetzner etc.) | ~€4/mo | Medium | On disk |
| Raspberry Pi | One-time ~$50 | Medium | On disk |

## Data

Spend data is stored locally in `./data/bot.db` (SQLite). The `data/` directory is volume-mounted in Docker so it persists across restarts. Back it up by copying the file.

## Development

```bash
pip install -r requirements.txt
python -m pytest test_bot.py -v
```

## Contributing

Contributions are welcome! Please open an issue first to discuss what you'd like to change.

1. Fork the repo
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Commit your changes (`git commit -m 'feat: describe change'`)
4. Push and open a pull request

Please make sure tests pass (`python -m pytest test_bot.py -v`) before submitting a PR.

## Code of Conduct

This project follows the [Contributor Covenant v2.1](https://www.contributor-covenant.org/version/2/1/code_of_conduct/). By participating you agree to uphold a welcoming, harassment-free environment.

## License

Distributed under the MIT License. See [LICENSE](LICENSE) for details.
