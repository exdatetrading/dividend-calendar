
"""Telegram dividend calendar notifications."""
import html
import json
import os
from datetime import datetime, timedelta
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from dividend_store import read_events, parse, ROOT

NOW = datetime.now(ZoneInfo("America/New_York"))
CALENDAR_URL = "https://exdatetrading.github.io/dividend-calendar/"


def trading_day(d):
    return d.weekday() < 5 and (d.month, d.day) not in (
        (1, 1), (12, 25)
    )


def prior(d):
    for _ in range(10):
        d -= timedelta(days=1)
        if trading_day(d):
            return d
    return d


def sources(row):
    url = str(
        row.get("sourceUrl") or row.get("source") or ""
    ).split(" | ")[0].strip()

    if not url.startswith(("https://", "http://")):
        return ""

    host = urlparse(url).netloc.lower()

    if "financialmodelingprep" in host:
        label = "FMP"
    elif "eodhd" in host:
        label = "EODHD"
    else:
        label = "Источник"

    return (
        f'🔎 <a href="{html.escape(url, quote=True)}">'
        f'{label}</a>'
    )


def events():
    rows = json.loads(
        (ROOT / "data.json").read_text(encoding="utf-8-sig")
    )

    bases = {
        str(r.get("ticker", "")).upper(): r
        for r in rows
        if isinstance(r, dict)
    }

    combined = []
    seen = set()

    for row in read_events() + rows:
        if not isinstance(row, dict):
            continue

        ticker = str(row.get("ticker", "")).strip()
        ex = parse(row.get("ex"))

        if not ticker or not ex:
            continue

        key = (ticker.upper(), str(ex))

        if key in seen:
            continue

        seen.add(key)
        base = bases.get(ticker.upper(), {})

        combined.append({
            "ticker": ticker,
            "name": str(base.get("name") or ticker),
            "ex": ex,
            "open": prior(ex),
            "source": row.get("source", ""),
            "sourceUrl": row.get("sourceUrl", ""),
            "exAdr": parse(row.get("exAdr")),
        })

    return sorted(
        combined,
        key=lambda e: (e["ex"], e["ticker"])
    )


def api(method, **kwargs):
    token = os.environ["TELEGRAM_BOT_TOKEN"]

    req = Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=urlencode(kwargs).encode(),
        method="POST",
    )

    with urlopen(req, timeout=30) as response:
        result = json.load(response)

    if not result.get("ok"):
        raise RuntimeError(
            result.get("description", "Telegram API error")
        )

    return result["result"]


def send(message):
    return api(
        "sendMessage",
        chat_id=os.environ["TELEGRAM_CHAT_ID"],
        text=message,
        parse_mode="HTML",
        disable_web_page_preview="true",
    )


def chunks(header, blocks, footer, limit=3700):
    out = []
    current = header

    for block in blocks:
        if len(header + block + footer) > limit:
            raise ValueError("Event block too long")

        if len(current + block + footer) > limit:
            out.append(current + footer)
            current = header

        current += block

    return out + [current + footer]


def label(e):
    ticker = html.escape(e["ticker"])
    name = html.escape(e["name"])

    if e["name"].upper() == e["ticker"].upper():
        return f"<b>{ticker}</b>"

    return f"<b>{ticker}</b> · {name}"


def footer():
    return (
        f'\n🔗 <a href="{CALENDAR_URL}">'
        "Календарь</a>"
    )


def monthly(all_events):
    selected = [
        e for e in all_events
        if (e["ex"].year, e["ex"].month)
        == (NOW.year, NOW.month)
    ]

    header = (
        f"📊 <b>EX-DATE TRADING · {NOW:%m.%Y}</b>\n"
        f"📌 Событий: {len(selected)}\n\n"
    )

    blocks = []

    for e in selected:
        block = (
            f"📍 {label(e)}\n"
            f'📅 Ex-date: <b>{e["ex"]:%d.%m.%Y}</b>\n'
            f'🔴 Ориентир SHORT: {e["open"]:%d.%m}\n'
        )

        if e["exAdr"]:
            block += f'ADR/ADS: {e["exAdr"]:%d.%m}\n'

        src = sources(e)

        if src:
            block += src + "\n"

        blocks.append(block + "\n")

    first = None

    messages = chunks(
        header,
        blocks or ["Нет событий с объявленной датой.\n"],
        footer(),
    )

    for message in messages:
        response = send(message)

        if first is None:
            first = response["message_id"]

    if first is not None:
        api(
            "pinChatMessage",
            chat_id=os.environ["TELEGRAM_CHAT_ID"],
            message_id=first,
            disable_notification="true",
        )

    print("Monthly posted:", len(selected))


def daily(all_events):
    today = NOW.date()

    groups = [
        (
            "🔴 ОРИЕНТИР SHORT",
            [e for e in all_events if e["open"] == today],
        ),
        (
            "📅 EX-DATE СЕГОДНЯ",
            [e for e in all_events if e["ex"] == today],
        ),
    ]

    if not any(group for _, group in groups):
        print("No events today")
        return

    blocks = []

    for title, group in groups:
        if not group:
            continue

        block = f"<b>{title}</b>\n"

        for e in group:
            block += (
                f'• {label(e)} · '
                f'Ex-date {e["ex"]:%d.%m}\n'
            )

            src = sources(e)

            if src:
                block += "  " + src + "\n"

        blocks.append(block + "\n")

    header = (
        f"📊 <b>EX-DATE TRADING · "
        f"{today:%d.%m.%Y}</b>\n\n"
    )

    for message in chunks(header, blocks, footer()):
        send(message)

    print("Daily posted")


def main():
    all_events = events()
    print("Loaded", len(all_events), "dated events")

    # Scheduled runs use New York time.
    # Manual runs are allowed at any hour.
    manual = (
        os.environ.get("GITHUB_EVENT_NAME")
        == "workflow_dispatch"
    )

    if not manual and NOW.hour != 9:
        print("Outside 09:00 New York window")
        return

    if NOW.day == 1:
        monthly(all_events)

    if NOW.weekday() < 5:
        daily(all_events)


if __name__ == "__main__":
    main()
