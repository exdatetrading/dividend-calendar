"""Send approved Telegram trade notifications. All times in America/New_York."""
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
now = datetime.now(ZoneInfo('America/New_York'))
# GitHub Actions schedule runs in UTC. Hourly check handles EST/EDT.
if now.hour != 9:
    print('Outside 09:00 New York window:', now.isoformat())
    sys.exit(0)

items = json.loads((ROOT / 'trades.json').read_text(encoding='utf-8'))['trades']
messages = []
for trade in items:
    if trade.get('approved') is not True:
        continue
    for key, label in [('open_date', 'Открытие'), ('close_date', 'Закрытие')]:
        if trade.get(key) != now.date().isoformat():
            continue
        ticker = trade['ticker'].strip().upper()
        if key == 'open_date':
            msg = (f'Всем привет!\n\nСегодня работаем с {ticker}.\n'
                   f'Открытие — до {trade.get("open_before", "16:00")} по Нью-Йорку.\n'
                   f'Ex-dividend — {trade["ex_date"]}.\n'
                   f'Планируемое закрытие — {trade["close_date"]} после {trade.get("close_after", "09:30")} по Нью-Йорку.')
        else:
            msg = (f'Всем привет!\n\nСегодня рассматриваем закрытие позиции {ticker} '
                   f'после {trade.get("close_after", "09:30")} по Нью-Йорку.')
        messages.append(msg)
if not messages:
    print('No approved trades scheduled for', now.date())
    sys.exit(0)

# Workflow runs hourly and could retry. Idempotency is not guaranteed; see README.
token = os.environ['TELEGRAM_BOT_TOKEN']
chat_id = os.environ['TELEGRAM_CHAT_ID']
body = '\n\n'.join(messages) + '\n\nДаты и условия уточняются перед торговлей. Дивиденды не гарантируют прибыль.'
request = Request(f'https://api.telegram.org/bot{token}/sendMessage',
                  data=urlencode({'chat_id': chat_id, 'text': body,
                                  'disable_web_page_preview': 'true'}).encode(),
                  method='POST')
with urlopen(request, timeout=20) as response:
    print('Telegram status:', response.status)
