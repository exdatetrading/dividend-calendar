"""Telegram calendar notifications sourced from data.json (not live market data)."""
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.now(ZoneInfo('America/New_York'))
CALENDAR_URL = 'https://mariabrownrr-cell.github.io/dividend-calendar/'
TIME_NOTE = '🕒 Все даты и время указаны по Нью-Йорку (ET).'
DISCLAIMER = 'Предварительный календарный план. Проверяйте даты, рынок и условия до торговли.'


def valid_date(value):
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def trading_day(day):
    """Weekday approximation, NOT an authoritative exchange holiday calendar."""
    if day.weekday() >= 5:
        return False
    # Major US closures relevant to the current calendar. Other markets differ.
    if (day.month, day.day) in ((1, 1), (12, 25)):
        return False
    if day.month == 11 and day.weekday() == 3 and 22 <= day.day <= 28:
        return False  # Thanksgiving
    return True


def adjacent_day(day, step):
    current = day
    for _ in range(14):
        current += timedelta(days=step)
        if trading_day(current):
            return current
    raise ValueError('Cannot find adjacent trading day')


def events():
    raw = json.loads((ROOT / 'data.json').read_text(encoding='utf-8'))
    if not isinstance(raw, list):
        raise ValueError('data.json must be a JSON array')
    out = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        ex = valid_date(item.get('ex'))
        if ex is None:
            continue
        ticker = str(item.get('platform') or item.get('ticker') or '').strip()
        if not ticker:
            continue
        # Use the primary listing date. ADR dates are shown separately, not conflated.
        out.append({
            'ticker': ticker,
            'exchange': str(item.get('ticker', ticker)),
            'market': str(item.get('market', '')),
            'ex': ex,
            'ex_adr': valid_date(item.get('exAdr')),
            'open': adjacent_day(ex, -1),
            'close': adjacent_day(ex, 1),
            'source': str(item.get('source', '')),
        })
    return sorted(out, key=lambda x: (x['ex'], x['ticker']))


def api(method, **kwargs):
    token = os.environ['TELEGRAM_BOT_TOKEN']
    req = Request(
        f'https://api.telegram.org/bot{token}/{method}',
        data=urlencode(kwargs).encode('utf-8'),
        method='POST',
    )
    with urlopen(req, timeout=30) as response:
        result = json.load(response)
    if not result.get('ok'):
        raise RuntimeError(result.get('description', 'Telegram API error'))
    return result['result']


def send(text):
    return api('sendMessage', chat_id=os.environ['TELEGRAM_CHAT_ID'],
               text=text, disable_web_page_preview='true')


def chunks(lines, limit=3700):
    result, current = [], ''
    for line in lines:
        if len(line) + 1 > limit:
            raise ValueError('One message line exceeds Telegram limit')
        if len(current) + len(line) + 1 > limit:
            result.append(current.rstrip())
            current = ''
        current += line + '\n'
    if current.strip():
        result.append(current.rstrip())
    return result


def monthly(all_events):
    selected = [e for e in all_events if (e['ex'].year, e['ex'].month) == (NOW.year, NOW.month)]
    lines = [f'📅 Дивидендный календарь — {NOW:%m.%Y}', '', TIME_NOTE,
             DISCLAIMER, '', f'Событий: {len(selected)}', '']
    if not selected:
        lines.append('Событий с объявленной датой Ex-dividend пока нет.')
    for e in selected:
        lines.extend([
            f"📌 {e['ticker']} ({e['exchange']}) — {e['market']}",
            f"🟢 Ориентир открытия: {e['open']:%d.%m.%Y}",
            f"📅 Ex-dividend: {e['ex']:%d.%m.%Y}",
            f"🔴 Ориентир закрытия: {e['close']:%d.%m.%Y}",
        ])
        if e['ex_adr']:
            lines.append(f"ADR/ADS Ex-dividend (если применимо): {e['ex_adr']:%d.%m.%Y}")
        lines.append('')
    lines.extend([f'Календарь: {CALENDAR_URL}', TIME_NOTE])
    first_id = None
    for part in chunks(lines):
        message = send(part)
        if first_id is None:
            first_id = message['message_id']
    api('pinChatMessage', chat_id=os.environ['TELEGRAM_CHAT_ID'],
            message_id=first_id, disable_notification='true')
    print(f'Monthly calendar posted and pinned; events={len(selected)}')


def daily(all_events):
    today = NOW.date()
    opens = [e for e in all_events if e['open'] == today]
    closes = [e for e in all_events if e['close'] == today]
    exs = [e for e in all_events if e['ex'] == today]
    if not (opens or closes or exs):
        print('No events today')
        return
    lines = [f'📅 Дивидендный календарь — {today:%d.%m.%Y}', '', TIME_NOTE,
             DISCLAIMER, '']
    for title, group in [('🟢 Ориентир открытия', opens),
                         ('📅 Ex-dividend сегодня', exs),
                         ('🔴 Ориентир закрытия', closes)]:
        if group:
            lines.extend([title + ':', ''])
            for e in group:
                lines.append(f"• {e['ticker']} ({e['exchange']}), Ex-dividend {e['ex']:%d.%m.%Y}")
            lines.append('')
    lines.extend([f'Календарь: {CALENDAR_URL}', TIME_NOTE])
    for part in chunks(lines):
        send(part)
    print(f'Daily: open={len(opens)} ex={len(exs)} close={len(closes)}')


def main():
    all_events = events()
    print(f'Loaded {len(all_events)} dated events from data.json')
    if os.environ.get('GITHUB_EVENT_NAME') == 'workflow_dispatch':
        monthly(all_events)
        return
    if NOW.hour != 9:
        print('Outside 09:00 New York window')
        return
    if NOW.day == 1:
        monthly(all_events)
    if NOW.weekday() < 5:
        daily(all_events)


if __name__ == '__main__':
    main()

