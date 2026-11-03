"""Conservative EODHD supplement for Ex-Date Trading.

Only confidently mapped exchange symbols are queried. Provider amounts are
reported for review, not silently written, because currency units can differ.
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data.json'
REPORT = ROOT / 'eodhd-sync-report.json'
STATE = ROOT / 'eodhd-sync-state.json'

# Verify new exchange codes against the provider before adding more.
MAP = {
    'ABDN': 'ABDN.LSE', 'ADS.DE': 'ADS.XETRA', 'AF.PA': 'AF.PA',
    'AI.PA': 'AI.PA', 'AIR.PA': 'AIR.PA', 'ALV.DE': 'ALV.XETRA',
    'BA.L': 'BA.LSE', 'BARC.L': 'BARC.LSE', 'BAS.DE': 'BAS.XETRA',
    'BAYN.DE': 'BAYN.XETRA', 'BMW.DE': 'BMW.XETRA', 'BNP.PA': 'BNP.PA',
    'BP.L': 'BP.LSE', 'BT-A.L': 'BT-A.LSE', 'CS.PA': 'CS.PA',
    'DBK.DE': 'DBK.XETRA', 'DHL.DE': 'DHL.XETRA', 'EOAN.DE': 'EOAN.XETRA',
    'GSK.L': 'GSK.LSE', 'IAG.L': 'IAG.LSE', 'III.L': 'III.LSE',
    'LLOY.L': 'LLOY.LSE', 'LSEG.L': 'LSEG.LSE', 'FRAS.L': 'FRAS.LSE',
    'VOD.L': 'VOD.LSE', 'SHEL.L': 'SHEL.LSE', 'RIO.L': 'RIO.LSE',
    'SAN.PA': 'SAN.PA', 'MC.PA': 'MC.PA', 'OR.PA': 'OR.PA',
    'SAP.DE': 'SAP.XETRA', 'SIE.DE': 'SIE.XETRA', 'VOW3.DE': 'VOW3.XETRA',
    'RNO.PA': 'RNO.PA', 'ULVR.L': 'ULVR.LSE', 'TSCO.L': 'TSCO.LSE',
    'RR.L': 'RR.LSE', 'SBRY.L': 'SBRY.LSE', 'TTE.PA': 'TTE.PA',
}
LIMIT = 10


def parse(value):
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def load_json(path, fallback):
    if not path.exists():
        return fallback
    return json.loads(path.read_text(encoding='utf-8-sig'))


def get(symbol, key, start, end):
    params = urllib.parse.urlencode({
        'api_token': key, 'fmt': 'json', 'from': str(start), 'to': str(end)
    })
    url = 'https://eodhd.com/api/div/' + urllib.parse.quote(symbol, safe='') + '?' + params
    req = urllib.request.Request(url, headers={'User-Agent': 'ExDateTrading-Sync/3.0'})
    with urllib.request.urlopen(req, timeout=30) as response:
        payload = json.load(response)
    if not isinstance(payload, list):
        raise ValueError('Unexpected API response format')
    return payload


def main():
    key = os.environ.get('EODHD_API_KEY', '').strip()
    if not key:
        raise RuntimeError('Missing EODHD_API_KEY')
    rows = load_json(DATA, None)
    if not isinstance(rows, list):
        raise RuntimeError('data.json is not an array')
    by_ticker = {str(r.get('ticker', '')).upper(): r for r in rows if isinstance(r, dict)}
    candidates = [(t, s) for t, s in MAP.items() if t.upper() in by_ticker]
    if not candidates:
        raise RuntimeError('No mapped instruments found in data.json')

    state = load_json(STATE, {})
    # Use a stable ticker marker if available, so extending MAP doesn't break rotation.
    last = state.get('next_ticker')
    candidate_names = [t for t, _ in candidates]
    if last in candidate_names:
        offset = candidate_names.index(last)
    else:
        offset = int(state.get('offset', 0)) % len(candidates)
    selected = (candidates[offset:] + candidates[:offset])[:LIMIT]
    today = date.today()
    start = today - timedelta(days=45)
    end = today + timedelta(days=370)
    report = {
        'date': str(today), 'window': {'from': str(start), 'to': str(end)},
        'mapped_instruments': len(candidates), 'request_limit': LIMIT,
        'checked': [], 'changed': [], 'review': [], 'errors': [],
        'unmapped_non_us': [r.get('ticker') for r in rows if isinstance(r, dict)
                            and r.get('market') != 'США' and str(r.get('ticker', '')) not in MAP],
        'note': 'Only verified mappings; one future dividend per ticker. Amounts require review.'
    }
    attempted = 0
    for ticker, symbol in selected:
        row = by_ticker[ticker.upper()]
        attempted += 1
        try:
            events = get(symbol, key, start, end)
        except (urllib.error.HTTPError, urllib.error.URLError, ValueError, TimeoutError) as exc:
            report['errors'].append({'ticker': ticker, 'symbol': symbol,
                                     'error': str(exc)[:160]})
            print('ERROR', ticker, type(exc).__name__)
            if isinstance(exc, urllib.error.HTTPError) and exc.code in (401, 402, 403, 429):
                break
            continue

        dated = sorted((e for e in events if isinstance(e, dict) and parse(e.get('date'))),
                       key=lambda e: e['date'])
        upcoming = [e for e in dated if today <= parse(e['date']) <= end]
        existing = parse(row.get('ex'))
        detail = {'ticker': ticker, 'symbol': symbol, 'events': len(events),
                  'future_events': len(upcoming),
                  'provider_dates': [e['date'] for e in upcoming[:5]],
                  'existing_ex': row.get('ex')}
        report['checked'].append(detail)
        if not upcoming:
            detail['decision'] = 'no_future_events'
            continue

        exact = next((e for e in upcoming if parse(e['date']) == existing), None)
        if existing and existing >= today and exact is None:
            detail['decision'] = 'future_date_conflict'
            report['review'].append({'ticker': ticker, 'reason': 'Different future ex-date',
                                     'existing': str(existing),
                                     'provider_dates': detail['provider_dates']})
            continue
        chosen = exact or upcoming[0]
        before = {k: row.get(k) for k in ('ex', 'pay', 'amount', 'currency')}
        if existing is None or existing < today:
            row['ex'] = chosen['date']
        payment = parse(chosen.get('paymentDate'))
        if payment and payment >= parse(row['ex']):
            row['pay'] = str(payment)

        # Do not modify dividend amounts without verifying GBX/GBP and ADR units.
        amount, currency = chosen.get('value'), chosen.get('currency')
        if amount is not None or currency:
            if str(amount) != str(row.get('amount', '')) or str(currency or '').upper() != str(row.get('currency', '')).upper():
                report['review'].append({
                    'ticker': ticker, 'reason': 'Provider amount/currency differ; verify units',
                    'provider_amount': amount, 'provider_currency': currency,
                    'stored_amount': row.get('amount'), 'stored_currency': row.get('currency'),
                    'ex_date': chosen['date']
                })
        after = {k: row.get(k) for k in before}
        if after != before:
            row['source'] = 'https://eodhd.com/api/div/' + urllib.parse.quote(symbol, safe='')
            row['dataStatus'] = 'EODHD provider data — verify issuer announcement'
            report['changed'].append({'ticker': ticker, 'symbol': symbol,
                                      'before': before, 'after': after})
            detail['decision'] = 'updated'
        else:
            detail['decision'] = 'already_current'

    next_offset = (offset + attempted) % len(candidates)
    state = {'offset': next_offset, 'next_ticker': candidates[next_offset][0],
             'mapped_instruments': len(candidates), 'daily_request_cap': LIMIT}
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if report['changed']:
        DATA.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('EODHD checked', len(report['checked']), 'changed', len(report['changed']),
          'reviews', len(report['review']), 'errors', len(report['errors']),
          'mapped', len(candidates), 'next', state['next_ticker'])
    for item in report['checked']:
        print('CHECKED', item['ticker'], item['decision'], 'future', item['future_events'])
    if report['errors'] and not report['checked']:
        raise RuntimeError('No successful EODHD requests; inspect report')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('EODHD sync failed:', str(exc), file=sys.stderr)
        sys.exit(1)
