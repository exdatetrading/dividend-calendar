"""Synchronize matching dividend events from FMP, preserving unmatched data."""
import json
import os
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data.json'
REPORT = ROOT / 'sync-report.json'
API = 'https://financialmodelingprep.com/stable/dividends-calendar'
MISSING = {'', '—', 'Не объявлена дата', 'null', 'None'}


def valid(s):
    if not isinstance(s, str):
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def get_events(start, end, key):
    query = urlencode({'from': start.isoformat(), 'to': end.isoformat(), 'apikey': key})
    request = Request(API + '?' + query, headers={'User-Agent': 'ExDateTrading-Sync/1.0'})
    with urlopen(request, timeout=35) as response:
        payload = json.load(response)
    if not isinstance(payload, list):
        raise RuntimeError('FMP did not return a list of events: ' + str(payload)[:220])
    return payload


def main():
    key = os.getenv('FMP_API_KEY')
    if not key:
        raise RuntimeError('Missing FMP_API_KEY GitHub Actions secret')
    records = json.loads(DATA.read_text(encoding='utf-8-sig'))
    if not isinstance(records, list):
        raise RuntimeError('data.json must contain a list')
    today = date.today()
    # Cover 30 days back for corrections and 180 days ahead for announcements.
    begin, end = today - timedelta(days=30), today + timedelta(days=180)
    events = []
    # Smaller date windows avoid provider range restrictions.
    cursor = begin
    while cursor <= end:
        stop = min(cursor + timedelta(days=29), end)
        events.extend(get_events(cursor, stop, key))
        cursor = stop + timedelta(days=1)
    by_symbol = defaultdict(list)
    for event in events:
        if not isinstance(event, dict):
            continue
        symbol = str(event.get('symbol') or '').strip().upper()
        ex = valid(event.get('date'))
        if symbol and ex and begin <= ex <= end:
            by_symbol[symbol].append(event)
    for entries in by_symbol.values():
        entries.sort(key=lambda e: e['date'])

    changes, reviews, unchanged, no_match = [], [], 0, 0
    for record in records:
        ticker = str(record.get('ticker') or '').strip()
        if not ticker:
            continue
        matches = by_symbol.get(ticker.upper(), [])
        if not matches:
            no_match += 1
            continue
        old = valid(record.get('ex'))
        future = [e for e in matches if valid(e['date']) >= today]
        if not future:
            unchanged += 1
            continue
        # Current schema stores only ONE event per instrument.
        # Prefer an exact existing date; otherwise next future date.
        exact = next((e for e in future if valid(e['date']) == old), None)
        chosen = exact or future[0]
        new_ex = chosen['date']
        # If old date is already in the future and differs, the provider may
        # be showing a later dividend, NOT a correction. Never overwrite it.
        if old and old >= today and old.isoformat() != new_ex:
            reviews.append({'ticker': ticker, 'reason': 'different future ex-date: possible separate dividend',
                            'existing': old.isoformat(), 'provider': new_ex})
            continue
        # Exact-symbol matching is not enough to establish exchange identity
        # for non-US securities and ADRs; require review.
        if record.get('market') != 'США' and not exact:
            reviews.append({'ticker': ticker, 'reason': 'non-US instrument / ADR needs exchange verification',
                            'existing': record.get('ex'), 'provider': new_ex})
            continue
        before = {k: record.get(k) for k in ('ex', 'pay', 'amount', 'currency')}
        if old is None or old < today:
            record['ex'] = new_ex
        payment = valid(chosen.get('paymentDate'))
        if payment and payment >= valid(record['ex']):
            record['pay'] = payment.isoformat()
        amount = chosen.get('adjDividend')
        if amount is None:
            amount = chosen.get('dividend')
        if amount is not None:
            try:
                if float(amount) > 0:
                    record['amount'] = str(amount)
            except (ValueError, TypeError):
                pass
        if record.get('market') == 'США' and record.get('currency') in MISSING:
            record['currency'] = 'USD'
        after = {k: record.get(k) for k in before}
        if after != before:
            record['source'] = API
            record['dataStatus'] = 'FMP provider data — verify issuer announcement'
            changes.append({'ticker': ticker, 'before': before, 'after': after})
        else:
            unchanged += 1

    report = {'checked_at_utc_date': today.isoformat(), 'window': [str(begin), str(end)],
              'instruments': len(records), 'api_events': len(events),
              'changed': changes, 'manual_review': reviews, 'no_matching_api_event': no_match,
              'unchanged': unchanged,
              'note': 'FMP coverage varies. No API match does not mean no dividend. One event per ticker in data.json.'}
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if changes:
        DATA.write_text(json.dumps(records, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Checked {len(records)} instruments; FMP events {len(events)}; changed {len(changes)}; review {len(reviews)}; no match {no_match}')
    for item in changes:
        print('UPDATED', item['ticker'], item['after'])
    for item in reviews[:40]:
        print('REVIEW', item['ticker'], item['reason'])


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'Sync failed: {exc}', file=sys.stderr)
        sys.exit(1)
