
"""Round-robin EODHD events; conservative symbol mappings and currency handling."""
import json
import os
import sys
import urllib.request
import urllib.parse
import urllib.error
from datetime import date, timedelta

from dividend_store import ROOT, parse, read_events, merge, write_events

# Mappings marked as candidates require exchange verification.
MAP = {
    'ABDN': 'ABDN.LSE',
    'ADS.DE': 'ADS.XETRA',
    'AF.PA': 'AF.PA',
    'AI.PA': 'AI.PA',
    'AIR.PA': 'AIR.PA',
    'ALV.DE': 'ALV.XETRA',
    'BA.L': 'BA.LSE',
    'BARC.L': 'BARC.LSE',
    'BAS.DE': 'BAS.XETRA',
    'BAYN.DE': 'BAYN.XETRA',
    'BMW.DE': 'BMW.XETRA',
    'BNP.PA': 'BNP.PA',
    'BP.L': 'BP.LSE',
    'BT-A.L': 'BT-A.LSE',
    'CS.PA': 'CS.PA',
    'DBK.DE': 'DBK.XETRA',
    'DHL.DE': 'DHL.XETRA',
    'EOAN.DE': 'EOAN.XETRA',
    'GSK.L': 'GSK.LSE',
    'IAG.L': 'IAG.LSE',
    'III.L': 'III.LSE',
    'LLOY.L': 'LLOY.LSE',
    'LSEG.L': 'LSEG.LSE',
    'FRAS.L': 'FRAS.LSE',
    'VOD.L': 'VOD.LSE',
    'SHEL.L': 'SHEL.LSE',
    'RIO.L': 'RIO.LSE',
    'SAN.PA': 'SAN.PA',
    'MC.PA': 'MC.PA',
    'OR.PA': 'OR.PA',
    'SAP.DE': 'SAP.XETRA',
    'SIE.DE': 'SIE.XETRA',
    'VOW3.DE': 'VOW3.XETRA',
    'RNO.PA': 'RNO.PA',
    'ULVR.L': 'ULVR.LSE',
    'TSCO.L': 'TSCO.LSE',
    'RR.L': 'RR.LSE',
    'SBRY.L': 'SBRY.LSE',
    'TTE.PA': 'TTE.PA',
}

# Disabled until exact EODHD exchange symbols are verified.
PENDING = {
    'ASML': 'ASML.AS',
    'COMMERZBANK': 'CBK.XETRA',
    'Centrica': 'CNA.LSE',
    'Danone': 'BN.PA',
    'EASYJET': 'EZJ.LSE',
    'Glencore': 'GLEN.LSE',
    'HSBC': 'HSBA.LSE',
    'IBE': 'IBE.MC',
    'IWG': 'IWG.LSE',
    'LUFTHANSA': 'LHA.XETRA',
    'Orange': 'ORA.PA',
    'PUMA': 'PUM.XETRA',
    'Quilter': 'QLT.LSE',
    'RHM': 'RHM.XETRA',
    'TUI': 'TUI1.XETRA',
    'VOD': 'VOD.LSE',
}

LIMIT = 10

def get(symbol, key, start, end):
    url = (
        'https://eodhd.com/api/div/'
        + urllib.parse.quote(symbol, safe='')
        + '?'
        + urllib.parse.urlencode({
            'api_token': key,
            'fmt': 'json',
            'from': str(start),
            'to': str(end)
        })
    )

    with urllib.request.urlopen(
        urllib.request.Request(
            url,
            headers={'User-Agent': 'ExDateTrading/4.0'}
        ),
        timeout=30
    ) as r:
        result = json.load(r)

    if not isinstance(result, list):
        raise ValueError('Unexpected EODHD response')

    return result

def main():
    key = os.environ['EODHD_API_KEY']

    rows = json.loads(
        (ROOT / 'data.json').read_text(encoding='utf-8-sig')
    )

    tickers = {
        str(r.get('ticker', '')).upper()
        for r in rows
        if isinstance(r, dict)
    }

    candidates = [
        (t, s)
        for t, s in MAP.items()
        if t.upper() in tickers
    ]

    state_path = ROOT / 'eodhd-sync-state.json'

    state = (
        json.loads(state_path.read_text())
        if state_path.exists()
        else {}
    )

    names = [t for t, _ in candidates]

    if not names:
        raise ValueError('No mapped tickers')

    offset = (
        names.index(state['next_ticker'])
        if state.get('next_ticker') in names
        else int(state.get('offset', 0)) % len(names)
    )

    selected = (
        candidates[offset:] + candidates[:offset]
    )[:LIMIT]

    today = date.today()
    start = today - timedelta(days=45)
    end = today + timedelta(days=370)

    report = {
        'date': str(today),
        'checked': [],
        'errors': [],
        'review': [],
        'pending_symbol_verification': {
            t: s
            for t, s in PENDING.items()
            if t.upper() in tickers
        }
    }

    incoming = []
    attempted = 0

    for ticker, symbol in selected:
        attempted += 1

        try:
            events = get(symbol, key, start, end)
        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            ValueError,
            TimeoutError
        ) as exc:
            report['errors'].append({
                'ticker': ticker,
                'error': str(exc)[:150]
            })

            if (
                isinstance(exc, urllib.error.HTTPError)
                and exc.code in (401, 402, 403, 429)
            ):
                break

            continue

        future = [
            e for e in events
            if isinstance(e, dict)
            and parse(e.get('date'))
            and today <= parse(e['date']) <= end
        ]

        report['checked'].append({
            'ticker': ticker,
            'symbol': symbol,
            'events': len(events),
            'future': len(future),
            'dates': [e['date'] for e in future]
        })

        for e in future:
            pay = (
                e.get('paymentDate')
                if parse(e.get('paymentDate'))
                else ''
            )

            # Avoid unverified GBX/GBP or ADR dividend amounts.
            incoming.append({
                'ticker': ticker,
                'ex': e['date'],
                'pay': pay,
                'amount': '',
                'currency': '',
                'source': (
                    'https://eodhd.com/api/div/'
                    + urllib.parse.quote(symbol, safe='')
                ),
                'provider': 'EODHD',
                'sourceUrl': 'https://eodhd.com/financial-apis/',
                'lastSeen': str(today)
            })

            if e.get('value') is not None:
                report['review'].append({
                    'ticker': ticker,
                    'ex': e['date'],
                    'amount': e.get('value'),
                    'currency': e.get('currency'),
                    'reason': 'Verify units before storing'
                })

    stored = read_events()
    added, enriched = merge(stored, incoming)
    write_events(stored)

    nxt = (offset + attempted) % len(candidates)

    state_path.write_text(
        json.dumps({
            'offset': nxt,
            'next_ticker': candidates[nxt][0],
            'mapped_instruments': len(candidates),
            'daily_request_cap': LIMIT
        }, indent=2) + '\n'
    )

    report.update({
        'added': added,
        'enriched': enriched,
        'total_stored': len(stored),
        'mapped_instruments': len(candidates)
    })

    (ROOT / 'eodhd-sync-report.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + '\n'
    )

    print(
        'EODHD checked', len(report['checked']),
        'added', added,
        'enriched', enriched,
        'errors', len(report['errors']),
        'next', candidates[nxt][0]
    )

    if report['errors'] and not report['checked']:
        raise RuntimeError('All EODHD requests failed')

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print('EODHD failed:', e, file=sys.stderr)
        sys.exit(1)
