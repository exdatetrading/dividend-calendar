#!/usr/bin/env python3
"""Read-only comparison of local dividend calendar against FMP."""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'fmp_comparison.json'
API = 'https://financialmodelingprep.com/stable/dividends-calendar'


def request_events(start, end, key):
    params = urllib.parse.urlencode({'from': start.isoformat(), 'to': end.isoformat(), 'apikey': key})
    req = urllib.request.Request(API + '?' + params, headers={'User-Agent': 'ExDateTrading-calendar-check/1.0'})
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            result = json.load(resp)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f'FMP HTTP {e.code} (check API access and limits)') from None
    if not isinstance(result, list):
        raise RuntimeError('Unexpected FMP response; calendar not changed')
    return result


def main():
    key = os.getenv('FMP_API_KEY')
    if not key:
        raise RuntimeError('FMP_API_KEY secret is missing')
    items = json.loads((ROOT / 'data.json').read_text(encoding='utf-8'))
    if not isinstance(items, list) or not items:
        raise RuntimeError('data.json must be a non-empty list')
    start = date.today()
    end = start + timedelta(days=90)
    # Request 30-day windows to avoid relying on large-range API behavior.
    raw = []
    cursor = start
    while cursor <= end:
        finish = min(cursor + timedelta(days=29), end)
        raw.extend(request_events(cursor, finish, key))
        cursor = finish + timedelta(days=1)
    by_symbol = defaultdict(list)
    for event in raw:
        if not isinstance(event, dict):
            continue
        sym = str(event.get('symbol') or '').strip().upper()
        when = str(event.get('date') or '')
        try:
            event_day = date.fromisoformat(when)
        except ValueError:
            continue
        if sym and start <= event_day <= end:
            by_symbol[sym].append(event)
    matches = []
    missing = []
    for item in items:
        ticker = str(item.get('ticker') or '').strip()
        # Exact symbols only; never map platform aliases, ADRs or exchanges automatically.
        found = sorted(by_symbol.get(ticker.upper(), []), key=lambda e: e['date'])
        if not found:
            missing.append(ticker)
            continue
        current = str(item.get('ex') or '')
        for event in found:
            matches.append({
                'ticker': ticker,
                'market': item.get('market'),
                'existing_ex': current,
                'fmp_ex': event.get('date'),
                'fmp_payment': event.get('paymentDate'),
                'fmp_dividend': event.get('dividend'),
                'status': 'same' if current == event.get('date') else ('new_date' if current == 'Не объявлена дата' else 'different_or_next_cycle'),
                'review_required': True,
            })
    report = {
        'mode': 'READ_ONLY_NO_CHANGES',
        'checked_from': start.isoformat(), 'checked_to': end.isoformat(),
        'calendar_instruments': len(items), 'fmp_events_returned': len(raw),
        'matched_events': len(matches), 'matched': matches,
        'no_exact_symbol_match': missing,
        'notes': [
            'FMP symbol equality does not verify exchange, currency or ADR identity.',
            'A different date can be a new dividend cycle, not a correction.',
            'No data.json edits, no Telegram messages.',
        ],
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Checked {len(items)} instruments; API events {len(raw)}; matched events {len(matches)}; no match {len(missing)}')
    print('Read-only comparison saved to fmp_comparison.json')
    for row in matches[:25]:
        print(f"{row['ticker']}: {row['existing_ex']} -> {row['fmp_ex']} ({row['status']})")


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        sys.exit(1)
