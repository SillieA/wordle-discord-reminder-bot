import json
import os
import random
import urllib.request
import urllib.error
from datetime import date, timezone, datetime

DISCORD_API_BASE = "https://discord.com/api/v10"

# Wordle epoch: puzzle #0 was on 2021-06-19
WORDLE_EPOCH = date(2021, 6, 19)
REMINDER_TEMPLATES = [
    "🟨🟩 **Wordle Reminder!** 🟩🟨\n\n{mentions}\n\nYou haven't posted your Wordle #{wordle_number} result yet! Get on it! 🧩",
    "⏰ {mentions} Wordle #{wordle_number} is waiting for you. Drop your score in the chat!",
    "🚨 {mentions} no Wordle #{wordle_number} post yet — time to solve and share!",
]


def get_wordle_number(today: date) -> int:
    """Return the Wordle puzzle number for a given date."""
    return (today - WORDLE_EPOCH).days


def discord_request(method: str, path: str, token: str, body: dict | None = None) -> dict:
    """Make an authenticated request to the Discord API."""
    url = f"{DISCORD_API_BASE}{path}"
    headers = {
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json",
        "User-Agent": "WordleReminderBot (https://github.com/SillieA/WordleReminderDiscordBot, 1.0)",
    }
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())


def get_recent_messages(channel_id: str, token: str) -> list[dict]:
    """Fetch the last 100 messages from a Discord channel."""
    return discord_request("GET", f"/channels/{channel_id}/messages?limit=100", token)


def find_wordle_completions(messages: list[dict], today: date) -> set[str]:
    """Return user IDs that have posted a Wordle result today."""
    today_str = today.isoformat()
    completed = set()
    for msg in messages:
        # Discord timestamps are ISO 8601, e.g. "2024-01-15T21:05:00.000000+00:00"
        timestamp = msg.get("timestamp", "")
        if not timestamp.startswith(today_str):
            continue
        content = msg.get("content", "")
        if "Wordle" in content and "/6" in content:
            author_id = msg.get("author", {}).get("id")
            if author_id:
                completed.add(author_id)
    return completed


def send_reminder(channel_id: str, token: str, user_ids: list[str], wordle_number: int) -> dict:
    """Send a reminder message mentioning the given users."""
    mentions = " ".join(f"<@{uid}>" for uid in user_ids)
    template = random.choice(REMINDER_TEMPLATES)
    content = template.format(mentions=mentions, wordle_number=wordle_number)
    body = {
        "content": content,
        "allowed_mentions": {
            "parse": [],
            "users": user_ids,
        },
    }
    return discord_request("POST", f"/channels/{channel_id}/messages", token, body)


def lambda_handler(event: dict, context) -> dict:
    """AWS Lambda entry point."""
    token = os.environ["DISCORD_TOKEN"]
    channel_id = os.environ["CHANNEL_ID"]
    user_ids = [uid.strip() for uid in os.environ["USER_IDS"].split(",") if uid.strip()]

    today = datetime.now(tz=timezone.utc).date()
    wordle_number = get_wordle_number(today)

    messages = get_recent_messages(channel_id, token)
    completed = find_wordle_completions(messages, today)

    if completed:
        print("At least one user has already posted their Wordle result. No reminder needed.")
        return {"statusCode": 200, "body": "No reminder needed"}

    print(f"Sending reminder to {len(user_ids)} user(s): {user_ids}")
    send_reminder(channel_id, token, user_ids, wordle_number)
    return {"statusCode": 200, "body": f"Reminder sent to {len(user_ids)} user(s)"}
