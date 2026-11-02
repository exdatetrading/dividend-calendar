
"""Monthly pinned calendar and daily trade notifications."""
import json
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.now(ZoneInfo("America/New_York"))
BOT = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT = os.environ.get("TELEGRAM_CHAT_ID")
CALENDAR_URL = "https://mariabrownrr-cell.github.io/dividend-calendar/"


def api(method, **kwargs):
    if not BOT or not CHAT:
        raise RuntimeError("Missing Telegram secrets")
    request = Request(
        f"https://api.telegram.org/bot{BOT}/{method}",
        data=urlencode(kwargs).encode("utf-8"),
        method="POST",
    )
    with urlopen(request, timeout=25) as response:
        result = json.load(response)
    if not result.get("ok"):
        raise RuntimeError(result.get("description"))
    return result["result"]


def send(text):
    return api(
        "sendMessage",
        chat_id=CHAT,
        text=text,
        disable_web_page_preview="true",
    )


def approved_trades():
    data = json.loads(
        (ROOT / "trades.json").read_text(encoding="utf-8")
    )
    return [t for t in data["trades"] if t.get("approved") is True]


def monthly(trades):
    month = NOW.strftime("%Y-%m")
    selected = sorted(
        [t for t in trades if t.get("open_date", "").startswith(month)],
        key=lambda t: (t["open_date"], t["ticker"]),
    )

    if not selected:
        print("No approved trades this month")
        return

    lines = [
        f"План сделок на {NOW.strftime('%m.%Y')}",
        "",
        "Открытие позиций:",
        "",
    ]

    for t in selected:
        date = datetime.fromisoformat(t["open_date"]).strftime("%d.%m")
        lines.append(
            f'{date} — {t["ticker"].upper()} '
            f'(Ex-dividend {t["ex_date"]})'
        )

    lines.extend([
        "",
        "Даты и условия уточняются перед торговлей.",
        f"Календарь: {CALENDAR_URL}",
    ])

    # Разбиваем длинный список на сообщения.
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
        chat_id=CHAT,
        message_id=first_id,
        disable_notification="true",
    )
    print("Monthly plan published and pinned")


def daily(trades):
    today = NOW.date().isoformat()

    openings = sorted(
        [t for t in trades if t.get("open_date") == today],
        key=lambda t: t["ticker"],
    )
    closings = sorted(
        [t for t in trades if t.get("close_date") == today],
        key=lambda t: t["ticker"],
    )

    if not openings and not closings:
        print("No trades today")
        return

    lines = [
        "Всем привет!",
        "",
        f"План на {NOW.strftime('%d.%m.%Y')}",
    ]

    if openings:
        lines.extend(["", "Открытие сделок:"])
        for t in openings:
            lines.append(
                f'{t["ticker"].upper()} — '
                f'до {t.get("open_before", "16:00")} '
                f'по Нью-Йорку.'
            )
            lines.append(f'Ex-dividend — {t["ex_date"]}.')
            lines.append(
                f'Закрытие — {t["close_date"]} '
                f'после {t.get("close_after", "09:30")}.'
            )

    if closings:
        lines.extend(["", "Планируемое закрытие:"])
        for t in closings:
            lines.append(
                f'{t["ticker"].upper()} — '
                f'после {t.get("close_after", "09:30")} '
                f'по Нью-Йорку.'
            )

    lines.extend([
        "",
        "Даты и условия проверяйте перед торговлей.",
        "Дивиденды не гарантируют прибыль.",
    ])

    message = "\n".join(lines)
    if len(message) > 4096:
        raise RuntimeError("Daily message exceeds Telegram limit")
    send(message)
    print("Daily message sent")


def main():
    # Ручной запуск отправляет только тест.
  if os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch":
    monthly(approved_trades())
    return
        )
        print("Test message sent")
        return

    # Проверяем время Нью-Йорка с учётом летнего времени.
    if NOW.hour != 9:
        print("Outside 09:00 New York window")
        return

    trades = approved_trades()

    # Первого числа публикуем и закрепляем месячный план.
    if NOW.day == 1:
        monthly(trades)

    # По будням публикуем сделки на сегодня.
    if NOW.weekday() < 5:
        daily(trades)


if __name__ == "__main__":
    main()
