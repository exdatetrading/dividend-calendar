
"""Telegram dividend notifications. Timezone: New York."""
import json
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.now(ZoneInfo("America/New_York"))
URL = "https://mariabrownrr-cell.github.io/dividend-calendar/"


def api(method, **kwargs):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    request = Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=urlencode(kwargs).encode("utf-8"),
        method="POST",
    )
    with urlopen(request, timeout=25) as response:
        result = json.load(response)

    if not result.get("ok"):
        raise RuntimeError(result.get("description", "Telegram API error"))
    return result["result"]


def send(message):
    return api(
        "sendMessage",
        chat_id=os.environ["TELEGRAM_CHAT_ID"],
        text=message,
        disable_web_page_preview="true",
    )


def trades():
    payload = json.loads(
        (ROOT / "trades.json").read_text(encoding="utf-8")
    )
    return [
        t for t in payload.get("trades", [])
        if t.get("approved") is True
    ]


def monthly(items):
    month = NOW.strftime("%Y-%m")
    selected = sorted(
        (
            t for t in items
            if t.get("open_date", "").startswith(month)
        ),
        key=lambda t: (t["open_date"], t["ticker"]),
    )

    if not selected:
        print("No approved monthly trades:", month)
        return

    lines = [
        f'План сделок на {NOW.strftime("%m.%Y")}',
        "",
        "Открытие позиций:",
        "",
    ]

    for t in selected:
        date = datetime.fromisoformat(
            t["open_date"]
        ).strftime("%d.%m")

        lines.append(
            f'{date} — {t["ticker"].upper()} '
            f'(Ex-dividend: {t["ex_date"]})'
        )

    lines.extend([
        "",
        "Даты проверяются перед торговлей.",
        f"Календарь: {URL}",
    ])

    chunks = []
    current = ""

    for line in lines:
        if len(current) + len(line) + 1 > 3800:
            chunks.append(current.rstrip())
            current = ""
        current += line + "\n"

    if current.strip():
        chunks.append(current.rstrip())

    first_id = None

    for chunk in chunks:
        result = send(chunk)
        if first_id is None:
            first_id = result["message_id"]

    api(
        "pinChatMessage",
        chat_id=os.environ["TELEGRAM_CHAT_ID"],
        message_id=first_id,
        disable_notification="true",
    )

    print("Monthly plan sent and pinned")


def daily(items):
    today = NOW.date().isoformat()

    openings = sorted(
        (t for t in items if t.get("open_date") == today),
        key=lambda t: t["ticker"],
    )

    closings = sorted(
        (t for t in items if t.get("close_date") == today),
        key=lambda t: t["ticker"],
    )

    if not openings and not closings:
        print("No approved trades today:", today)
        return

    lines = [
        "Всем привет!",
        "",
        f'План на {NOW.strftime("%d.%m.%Y")}',
    ]

    if openings:
        lines.extend(["", "Открытие сделок:"])

        for t in openings:
            lines.append(
                f'{t["ticker"].upper()} — до '
                f'{t.get("open_before", "16:00")} '
                "по Нью-Йорку."
            )
            lines.append(
                f'Ex-dividend — {t["ex_date"]}.'
            )
            lines.append(
                f'Закрытие — {t["close_date"]} после '
                f'{t.get("close_after", "09:30")} '
                "по Нью-Йорку."
            )

    if closings:
        lines.extend(["", "Планируемое закрытие:"])

        for t in closings:
            lines.append(
                f'{t["ticker"].upper()} — после '
                f'{t.get("close_after", "09:30")} '
                "по Нью-Йорку."
            )

    lines.extend([
        "",
        "Даты и условия проверяйте перед торговлей.",
        "Дивиденды не гарантируют прибыль.",
    ])

    message = "\n".join(lines)

    if len(message) > 4096:
        raise ValueError("Telegram message too long")

    send(message)
    print("Daily notification sent")


def main():
    items = trades()

    # Ручной запуск: публикуем и закрепляем месячный план.
    if os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch":
        monthly(items)
        return

    # Автоматическая рассылка в 09:00 по Нью-Йорку.
    if NOW.hour != 9:
        print("Outside 09:00 New York window")
        return

    # Первого числа — месячный план.
    if NOW.day == 1:
        monthly(items)

    # В будни — ежедневные уведомления.
    if NOW.weekday() < 5:
        daily(items)


if __name__ == "__main__":
    main()
