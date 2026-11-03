"""FMP dividend calendar sync: add all announced dates without overwriting legacy data."""
import json,os,sys
from collections import defaultdict
from datetime import date,timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from dividend_store import ROOT,parse,read_events,merge,write_events
API='https://financialmodelingprep.com/stable/dividends-calendar'

def get(start,end,key):
    url=API+'?'+urlencode({'from':str(start),'to':str(end),'apikey':key})
    with urlopen(Request(url,headers={'User-Agent':'ExDateTrading/4.0'}),timeout=35) as r: data=json.load(r)
    if not isinstance(data,list): raise ValueError('Unexpected FMP response')
    return data

def main():
    key=os.environ['FMP_API_KEY']
    rows=json.loads((ROOT/'data.json').read_text(encoding='utf-8-sig'))
    today=date.today();begin=today-timedelta(days=30);end=today+timedelta(days=180)
    events=[];cursor=begin
    while cursor<=end:
        stop=min(cursor+timedelta(days=29),end);events.extend(get(cursor,stop,key));cursor=stop+timedelta(days=1)
    by_symbol=defaultdict(list)
    for e in events:
        if isinstance(e,dict) and parse(e.get('date')) and parse(e['date'])>=today:
            by_symbol[str(e.get('symbol','')).upper()].append(e)
    incoming=[];reviews=[]
    for row in rows:
        if not isinstance(row,dict):continue
        ticker=str(row.get('ticker','')).strip()
        # Avoid ambiguous international tickers and ADR symbol collisions.
        if row.get('market')!='США':continue
        for e in by_symbol.get(ticker.upper(),[]):
            pay=e.get('paymentDate') if parse(e.get('paymentDate')) else ''
            amount=e.get('adjDividend') if e.get('adjDividend') is not None else e.get('dividend')
            incoming.append({'ticker':ticker,'ex':e['date'],'pay':pay,'amount':str(amount) if amount is not None else '',
                'currency':'USD','source':API,'provider':'FMP','sourceUrl':API})
    stored=read_events();added,enriched=merge(stored,incoming);write_events(stored)
    report={'date':str(today),'api_events':len(events),'matched_events':len(incoming),'added':added,'enriched':enriched,
            'total_stored':len(stored),'note':'Additional events stored separately. Legacy data.json unchanged. USD assumed for US listings; verify issuer and dividend units.'}
    (ROOT/'sync-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('FMP events',len(events),'matched',len(incoming),'added',added,'enriched',enriched)
if __name__=='__main__':
    try:main()
    except Exception as e:print('FMP failed:',e,file=sys.stderr);sys.exit(1)
