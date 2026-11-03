"""Telegram calendar notifications with per-event provenance."""
import html,json,os
from datetime import date,datetime,timedelta
from pathlib import Path
from urllib.parse import urlencode,urlparse
from urllib.request import Request,urlopen
from zoneinfo import ZoneInfo
from dividend_store import read_events,parse,ROOT
NOW=datetime.now(ZoneInfo('America/New_York'))
CALENDAR_URL='https://exdatetrading.github.io/dividend-calendar/'
NOTE='⚠️ Даты предварительные. Торговые дни и часы зависят от биржи. SHORT перед ex-date не гарантирует прибыль: учитывайте дивидендные компенсации, комиссии и доступность займа.'

def trading_day(d):
    # Approximation only; do not advertise exchange-specific execution times.
    return d.weekday()<5 and (d.month,d.day) not in ((1,1),(12,25))

def prior(d):
    for _ in range(10):
        d-=timedelta(days=1)
        if trading_day(d):return d
    return d

def sources(row):
    url=str(row.get('sourceUrl') or row.get('source') or '').split(' | ')[0].strip()
    if not url.startswith(('https://','http://')):return ''
    host=urlparse(url).netloc.lower()
    if 'financialmodelingprep' in host:label='FMP'
    elif 'eodhd' in host:label='EODHD'
    else:label='Источник'
    return f'🔎 <a href="{html.escape(url,quote=True)}">{label}</a> (проверьте объявление эмитента)'

def events():
    rows=json.loads((ROOT/'data.json').read_text(encoding='utf-8-sig'))
    combined=[];seen=set()
    # Extra events take priority when same ticker+ex-date is present in both datasets.
    for row in read_events()+rows:
        if not isinstance(row,dict):continue
        ticker=str(row.get('ticker','')).strip();ex=parse(row.get('ex'))
        if not ticker or not ex:continue
        key=(ticker.upper(),str(ex))
        if key in seen:continue
        seen.add(key)
        base=next((r for r in rows if isinstance(r,dict) and str(r.get('ticker','')).upper()==ticker.upper()),{})
        combined.append({'ticker':ticker,'name':str(base.get('name') or ticker),'ex':ex,
                         'open':prior(ex),'close':ex,'source':row.get('source',''),
                         'sourceUrl':row.get('sourceUrl',''),'exAdr':parse(row.get('exAdr'))})
    return sorted(combined,key=lambda e:(e['ex'],e['ticker']))

def api(method,**kwargs):
    token=os.environ['TELEGRAM_BOT_TOKEN']
    req=Request(f'https://api.telegram.org/bot{token}/{method}',data=urlencode(kwargs).encode(),method='POST')
    with urlopen(req,timeout=30) as r:result=json.load(r)
    if not result.get('ok'):raise RuntimeError(result.get('description','Telegram API error'))
    return result['result']

def send(message):return api('sendMessage',chat_id=os.environ['TELEGRAM_CHAT_ID'],text=message,parse_mode='HTML',disable_web_page_preview='true')

def chunks(header,blocks,footer,limit=3700):
    out=[];current=header
    for block in blocks:
        if len(header+block+footer)>limit:raise ValueError('Event block too long')
        if len(current+block+footer)>limit:out.append(current+footer);current=header
        current+=block
    return out+[current+footer]

def label(e):
    t=html.escape(e['ticker']);n=html.escape(e['name'])
    return f'<b>{t}</b>' if e['name'].upper()==e['ticker'].upper() else f'<b>{t}</b> · {n}'

def footer():return f'\n🔗 <a href="{CALENDAR_URL}">Календарь</a>\n\n<i>{html.escape(NOTE)}</i>'

def monthly(all_events):
    selected=[e for e in all_events if (e['ex'].year,e['ex'].month)==(NOW.year,NOW.month)]
    header=f'📊 <b>EX-DATE TRADING · {NOW:%m.%Y}</b>\n📌 Событий: {len(selected)}\n\n'
    blocks=[]
    for e in selected:
        block=f'📍 {label(e)}\n📅 Ex-date: <b>{e["ex"]:%d.%m.%Y}</b>\n'
        block+=f'🔴 Ориентир SHORT: {e["open"]:%d.%m} · 🟢 Ex-date: {e["close"]:%d.%m}\n'
        if e['exAdr']:block+=f'ADR/ADS: {e["exAdr"]:%d.%m}\n'
        src=sources(e)
        if src:block+=src+'\n'
        blocks.append(block+'\n')
    first=None
    for msg in chunks(header,blocks or ['Нет событий с объявленной датой.\n'],footer()):
        response=send(msg)
        if first is None:first=response['message_id']
    api('pinChatMessage',chat_id=os.environ['TELEGRAM_CHAT_ID'],message_id=first,disable_notification='true')
    print('Monthly posted',len(selected))

def daily(all_events):
    today=NOW.date();groups=[('🔴 ОРИЕНТИР SHORT',[e for e in all_events if e['open']==today]),
      ('📅 EX-DATE СЕГОДНЯ',[e for e in all_events if e['ex']==today])]
    if not any(g for _,g in groups):print('No events today');return
    blocks=[]
    for title,group in groups:
        if not group:continue
        block=f'<b>{title}</b>\n'
        for e in group:
            block+=f'• {label(e)} · Ex-date {e["ex"]:%d.%m}\n'
            src=sources(e)
            if src:block+='  '+src+'\n'
        blocks.append(block+'\n')
    for msg in chunks(f'📊 <b>EX-DATE TRADING · {today:%d.%m.%Y}</b>\n\n',blocks,footer()):send(msg)
    print('Daily posted')

def main():
    all_events=events();print('Loaded',len(all_events),'dated events')
    if os.environ.get('GITHUB_EVENT_NAME')=='workflow_dispatch':monthly(all_events);return
    if NOW.hour!=9:return
    if NOW.day==1:monthly(all_events)
    if NOW.weekday()<5:daily(all_events)
if __name__=='__main__':main()
