"""Shared event store. Legacy data.json remains authoritative for existing rows."""
import json
from datetime import date
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
EVENTS=ROOT/'dividend-events.json'

def parse(s):
    try: return date.fromisoformat(str(s))
    except (ValueError,TypeError): return None

def read_events():
    if not EVENTS.exists(): return []
    value=json.loads(EVENTS.read_text(encoding='utf-8-sig'))
    if not isinstance(value,list): raise ValueError('dividend-events.json must be array')
    return value

def merge(current, incoming):
    """Merge by ticker+ex-date; never delete old entries or replace existing known values."""
    idx={(str(x.get('ticker','')).upper(),x.get('ex')):x for x in current if isinstance(x,dict)}
    added=0; enriched=0
    for e in incoming:
        key=(str(e.get('ticker','')).upper(),e.get('ex'))
        if not key[0] or not parse(key[1]): continue
        if key not in idx:
            new=dict(e);current.append(new);idx[key]=new;added+=1
        else:
            old=idx[key]; touched=False
            for field in ('pay','amount','currency','source','provider','sourceUrl'):
                if old.get(field) in (None,'','—','Не объявлена дата') and e.get(field) not in (None,'','—','Не объявлена дата'):
                    old[field]=e[field];touched=True
            if touched: enriched+=1
    current.sort(key=lambda x:(str(x.get('ex','')),str(x.get('ticker',''))))
    return added,enriched

def write_events(items):
    EVENTS.write_text(json.dumps(items,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
