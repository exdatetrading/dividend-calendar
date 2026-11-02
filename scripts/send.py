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
if os.environ.get('GITHUB_EVENT_NAME') == 'workflow_dispatch':
    token = os.environ['TELEGRAM_BOT_TOKEN']
    chat_id = os.environ['TELEGRAM_CHAT_ID']

    body = (
        'Тестовое уведомление Ex-Date Trading\n\n'
        'Telegram-бот успешно подключён.\n'
        'Автоматическая рассылка дивидендных сделок настроена.\n\n'
        'Календарь: https://mariabrownrr-cell.github.io/dividend-calendar/'
    )

    request = Request(
        f'https://api.telegram.org/bot{token}/sendMessage',
        data=urlencode({
            'chat_id': chat_id,
            'text': body
        }).encode(),
        method='POST'
    )

    with urlopen(request, timeout=20) as response:
        print('Test message status:', response.status)

    sys.exit(0)
