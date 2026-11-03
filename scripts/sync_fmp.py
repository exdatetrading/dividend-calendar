#!/usr/bin/env python3
"""Conservative FMP sync: fill missing US ex-dates only; never overwrite known dates."""
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data.json"
REPORT = ROOT / "fmp_sync_report.json"
API = "https://financialmodelingprep.com/stable/dividends-calendar"
UNKNOWN = "Не объявлена дата"
# Explicitly exclude foreign/ADR instruments even if marked US by mistake.
EXCLUDED = {"AZN", "BABA", "LYG", "HSBC", "BNTX", "ASML", "GSK.L"}


def valid_day(value):
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def fetch(key, start, end):
    query = urllib.parse.urlencode({"from": start.isoformat(), "to": end.isoformat(), "apikey": key})
    req = urllib.request.Request(API + "?" + query, headers={"User-Agent": "ExDateTrading/1.0"})
    with urllib.request.urlopen(req, timeout=40) as resp:
        data = json.load(resp)
    if not isinstance(data, list):
        raise ValueError("Unexpected FMP response; refusing to modify calendar")
    return data


def main():
    key = os.environ.get("FMP_API_KEY")
    if not key:
        raise ValueError("FMP_API_KEY missing")
    items = json.loads(DATA.read_text(encoding="utf-8"))
    if not isinstance(items, list) or not items or any(not isinstance(i, dict) for i in items):
        raise ValueError("Invalid data.json; refusing to modify")
    today = date.today()
    end = today + timedelta(days=89)
    raw = []
    cursor = today
    while cursor <= end:
        finish = min(cursor + timedelta(days=29), end)
        raw.extend(fetch(key, cursor, finish))
        cursor = finish + timedelta(days=1)
    # A missing date is filled only when exactly one valid future FMP event exists
    # for the exact ticker. Multiple events or ambiguous symbols go to review.
    by_symbol = {}
    for event in raw:
        if not isinstance(event, dict):
            continue
        sym = event.get("symbol")
        d = valid_day(event.get("date"))
        if isinstance(sym, str) and d and today <= d <= end:
            by_symbol.setdefault(sym.strip().upper(), []).append(event)
    updated = []
    review = []
    for item in items:
        ticker = str(item.get("ticker", "")).strip().upper()
        if item.get("ex") != UNKNOWN or item.get("market") != "США":
            continue
        if ticker in EXCLUDED or not re.fullmatch(r"[A-Z]{1,5}", ticker):
            continue
        matches = by_symbol.get(ticker, [])
        # Deduplicate repeated identical provider records.
        unique = {e["date"]: e for e in matches}
        if len(unique) != 1:
            if len(unique) > 1:
                review.append({"ticker": ticker, "reason": "multiple future dates", "dates": sorted(unique)})
            continue
        event = next(iter(unique.values()))
        ex = event["date"]
        payment = valid_day(event.get("paymentDate"))
        if payment and payment < date.fromisoformat(ex):
            review.append({"ticker": ticker, "reason": "payment before ex", "date": ex})
            continue
        # Do not copy provider amounts: currency/share class may differ.
        item["ex"] = ex
        if payment and item.get("pay") in (None, "", UNKNOWN):
            item["pay"] = payment.isoformat()
        item["source"] = "https://financialmodelingprep.com/stable/dividends-calendar"
        item["dataStatus"] = "FMP provider data — verify issuer announcement"
        updated.append({"ticker": ticker, "ex": ex, "payment": payment.isoformat() if payment else None})
    if len(updated) > 15:
        raise ValueError(f"Safety limit: {len(updated)} updates in one run; refusing to write")
    REPORT.write_text(json.dumps({"checked": today.isoformat(), "provider_events": len(raw), "updated": updated, "review": review, "notes": "US exact symbols only; missing dates only; no existing dates overwritten"}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if updated:
        DATA.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"FMP events: {len(raw)}; new US dates saved: {len(updated)}; manual review: {len(review)}")
    for row in updated:
        print(row["ticker"], row["ex"])


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"SYNC FAILED (calendar unchanged unless write completed): {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
