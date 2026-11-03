"""Ex-Date Trading: Telegram notifications from data.json."""
import html
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.now(ZoneInfo('America/New_York'))
CALENDAR_URL = 'https://exdatetrading.github.io/dividend-calendar/'
NOTE = '🕒 Даты — по календарю соответствующей биржи. Для акций США ориентир: SHORT перед закрытием предыдущей сессии, закрытие SHORT в первые минуты после открытия в ex-date. Даты предварительные; проверяйте биржевые праздники, объявления эмитентов, возможность шорта и расходы по дивиденду.'


def valid_date(value):
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def trading_day(day):
    # Approximate US weekday calendar; non-US exchanges may have other holidays.
    # Must be replaced with exchange-specific calendars before relying on timings.
    if day.weekday() >= 5 or (day.month, day.day) in ((1, 1), (12, 25)):
        return False
    if day.month == 11 and day.weekday() == 3 and 22 <= day.day <= 28:
        return False
    return True


def adjacent_day(day, step):
    for _ in range(14):
        day += timedelta(days=step)
        if trading_day(day):
            return day
    raise ValueError('Cannot find adjacent trading day')


def events():
    raw = json.loads((ROOT / 'data.json').read_text(encoding='utf-8'))
    if not isinstance(raw, list):
        raise ValueError('data.json must be a JSON array')
    result = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        ex = valid_date(item.get('ex'))
        ticker = str(item.get('ticker') or '').strip()
        if not ex or not ticker:
            continue
        result.append({
            'ticker': ticker,
            'name': str(item.get('name') or ticker),
            'market': str(item.get('market') or ''),
            'ex': ex,
            'ex_adr': valid_date(item.get('exAdr')),
            'open': adjacent_day(ex, -1),
            'close': ex,
        })
    return sorted(result, key=lambda x: (x['ex'], x['ticker']))


def api(method, **kwargs):
    token = os.environ['TELEGRAM_BOT_TOKEN']
    request = Request(
        f'https://api.telegram.org/bot{token}/{method}',
        data=urlencode(kwargs).encode('utf-8'), method='POST')
    with urlopen(request, timeout=30) as response:
        payload = json.load(response)
    if not payload.get('ok'):
        raise RuntimeError(payload.get('description', 'Telegram API error'))
    return payload['result']


def send(message):
    return api('sendMessage', chat_id=os.environ['TELEGRAM_CHAT_ID'],
               text=message, parse_mode='HTML', disable_web_page_preview='true')


def split_blocks(header, blocks, footer, limit=3700):
    """Split only between complete HTML blocks, keeping tags balanced."""
    parts = []
    current = header
    for block in blocks:
        if len(header + block + footer) > limit:
            raise ValueError('One event block exceeds Telegram message limit')
        if len(current + block + footer) > limit:
            parts.append(current + footer)
            current = header
        current += block
    parts.append(current + footer)
    return parts


def item_label(e):
    name = html.escape(e['name'])
    ticker = html.escape(e['ticker'])
    return f'<b>{ticker}</b>' if name.upper() == e['ticker'].upper() else f'<b>{ticker}</b> · {name}'


def link_footer():
    return f'\n🔗 <a href="{CALENDAR_URL}">Открыть полный календарь</a>\n\n<i>{NOTE}</i>'


def monthly(all_events):
    selected = [e for e in all_events if (e['ex'].year, e['ex'].month) == (NOW.year, NOW.month)]
    header = (f'📊 <b>EX-DATE TRADING</b>\n'
              f'<b>ДИВИДЕНДНЫЙ КАЛЕНДАРЬ · {NOW:%m.%Y}</b>\n'
              f'━━━━━━━━━━━━━━\n'
              f'📌 Событий: <b>{len(selected)}</b>\n\n')
    blocks = []
    for e in selected:
        block = (f'📍 {item_label(e)}\n'
                 f'🔴 SHORT · перед закрытием: <b>{e["open"]:%d.%m}</b>\n'
                 f'📅 Ex-date: <b>{e["ex"]:%d.%m}</b>\n'
                 f'🟢 Закрытие · после открытия: <b>{e["close"]:%d.%m}</b>\n')
        if e['ex_adr']:
            block += f'ADR/ADS: {e["ex_adr"]:%d.%m}\n'
        blocks.append(block + '\n')
    if not blocks:
        blocks = ['Пока нет событий с объявленной датой.\n']
    first_id = None
    for part in split_blocks(header, blocks, link_footer()):
        result = send(part)
        if first_id is None:
            first_id = result['message_id']
    api('pinChatMessage', chat_id=os.environ['TELEGRAM_CHAT_ID'],
        message_id=first_id, disable_notification='true')
    print(f'Monthly posted and pinned; events={len(selected)}')


def daily(all_events):
    today = NOW.date()
    groups = [
        ('🔴 <b>ОТКРЫТИЕ SHORT · ПЕРЕД ЗАКРЫТИЕМ РЫНКА</b>', [e for e in all_events if e['open'] == today], 'ex'),
        ('📅 <b>EX-DIVIDEND СЕГОДНЯ</b>', [e for e in all_events if e['ex'] == today], 'ex'),
        ('🟢 <b>ЗАКРЫТИЕ SHORT · ПОСЛЕ ОТКРЫТИЯ РЫНКА</b>', [e for e in all_events if e['close'] == today], 'ex'),
    ]
    if not any(group for _, group, _ in groups):
        print('No events today')
        return
    header = (f'📊 <b>EX-DATE TRADING</b>\n'
              f'<b>ПЛАН НА {today:%d.%m.%Y}</b>\n'
              f'━━━━━━━━━━━━━━\n\n')
    blocks = []
    for title, group, _ in groups:
        if not group:
            continue
        block = title + '\n'
        for e in group:
            block += f'• {item_label(e)} · Ex-date {e["ex"]:%d.%m}\n'
        blocks.append(block + '\n')
    for part in split_blocks(header, blocks, link_footer()):
        send(part)
    print('Daily posted')


def main():
    all_events = events()
    print(f'Loaded {len(all_events)} dated events')
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
