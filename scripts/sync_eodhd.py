"""Conservative supplemental EODHD dividend sync. FMP sync runs separately first."""
import json, os, sys, urllib.request, urllib.parse, urllib.error
from pathlib import Path
from datetime import date, timedelta

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data.json'
REPORT=ROOT/'eodhd-sync-report.json'
STATE=ROOT/'eodhd-sync-state.json'
# Explicit exchange-verified symbol mappings. Never guess from company name.
MAP={
 'ABDN':'ABDN.LSE','ADS.DE':'ADS.XETRA','AF.PA':'AF.PA','AI.PA':'AI.PA',
 'AIR.PA':'AIR.PA','ALV.DE':'ALV.XETRA','BA.L':'BA.LSE','BARC.L':'BARC.LSE',
 'BAS.DE':'BAS.XETRA','BAYN.DE':'BAYN.XETRA','BMW.DE':'BMW.XETRA',
 'BNP.PA':'BNP.PA','BP.L':'BP.LSE','BT-A.L':'BT-A.LSE','CS.PA':'CS.PA',
 'DBK.DE':'DBK.XETRA','DHL.DE':'DHL.XETRA','EOAN.DE':'EOAN.XETRA',
 'GSK.L':'GSK.LSE','IAG.L':'IAG.LSE','III.L':'III.LSE',
 'LLOY.L':'LLOY.LSE','LSEG.L':'LSEG.LSE','FRAS.L':'FRAS.LSE',
 'VOD.L':'VOD.LSE','SHEL.L':'SHEL.LSE','RIO.L':'RIO.LSE',
 'SAN.PA':'SAN.PA','MC.PA':'MC.PA','OR.PA':'OR.PA','SAP.DE':'SAP.XETRA',
 'SIE.DE':'SIE.XETRA','VOW3.DE':'VOW3.XETRA',
}
# Conservative daily cap; can be adjusted after verifying plan limits.
LIMIT=10

def parse(x):
 try: return date.fromisoformat(str(x))
 except (TypeError,ValueError): return None

def get(symbol,key,start,end):
 params=urllib.parse.urlencode({'api_token':key,'fmt':'json','from':str(start),'to':str(end)})
 url='https://eodhd.com/api/div/'+urllib.parse.quote(symbol,safe='')+'?'+params
 req=urllib.request.Request(url,headers={'User-Agent':'ExDateTrading-Sync/2.0'})
 with urllib.request.urlopen(req,timeout=30) as response: payload=json.load(response)
 if not isinstance(payload,list): raise ValueError('Unexpected API response format')
 return payload

def main():
 key=os.environ.get('EODHD_API_KEY','').strip()
 if not key: raise RuntimeError('Missing EODHD_API_KEY')
 rows=json.loads(DATA.read_text(encoding='utf-8-sig'))
 if not isinstance(rows,list): raise RuntimeError('data.json is not an array')
 byticker={str(r.get('ticker','')).upper():r for r in rows if isinstance(r,dict)}
 candidates=[(t,s) for t,s in MAP.items() if t.upper() in byticker]
 state=json.loads(STATE.read_text()) if STATE.exists() else {}
 offset=int(state.get('offset',0))%max(1,len(candidates))
 selected=(candidates[offset:]+candidates[:offset])[:LIMIT]
 today=date.today(); start=today-timedelta(days=45); end=today+timedelta(days=370)
 report={'date':str(today),'checked':[],'changed':[],'review':[],'errors':[],
         'unmapped_non_us':[r.get('ticker') for r in rows if r.get('market')!='США' and str(r.get('ticker','')) not in MAP],
         'note':'Only explicitly mapped symbols. No speculative dates. One dividend event per ticker.'}
 for ticker,symbol in selected:
  row=byticker[ticker.upper()]
  try:
   events=get(symbol,key,start,end)
  except (urllib.error.HTTPError,urllib.error.URLError,ValueError) as e:
   report['errors'].append({'ticker':ticker,'symbol':symbol,'error':str(e)[:150]})
   print('ERROR',ticker,type(e).__name__)
   if isinstance(e,urllib.error.HTTPError) and e.code in (401,402,403,429):
    print('Stopping early due to API access/quota error'); break
   continue
  report['checked'].append({'ticker':ticker,'symbol':symbol,'events':len(events)})
  upcoming=sorted([e for e in events if isinstance(e,dict) and parse(e.get('date')) and today<=parse(e['date'])<=end],key=lambda e:e['date'])
  if not upcoming: continue
  existing=parse(row.get('ex'))
  exact=next((e for e in upcoming if parse(e['date'])==existing),None)
  # If an existing future event differs, we cannot know if it's a correction or next dividend.
  if existing and existing>=today and not exact:
   report['review'].append({'ticker':ticker,'reason':'Different future ex-date','existing':str(existing),'provider':upcoming[0]['date']})
   continue
  chosen=exact or upcoming[0]
  before={k:row.get(k) for k in ('ex','pay','amount','currency')}
  if not existing or existing<today: row['ex']=chosen['date']
  payment=parse(chosen.get('paymentDate'))
  if payment and payment>=parse(row['ex']):
   # A payment date for a matching ex-date can safely replace the existing one.
   row['pay']=str(payment)
  # Provider dividend units differ across exchanges (GBP/GBX etc).
  # Do not silently change existing amount or currency; fill only when both missing
  # and provider supplies an explicit currency. Flag for verification.
  amount=chosen.get('value'); currency=chosen.get('currency')
  if str(row.get('amount','')).strip()=='' and str(row.get('currency','')).strip()=='' and currency and amount is not None:
   try:
    if float(amount)>0 and str(currency).upper() in ('EUR','GBP','GBX','CHF','USD','CAD','AUD'):
     row['amount']=str(amount); row['currency']=str(currency).upper()
     report['review'].append({'ticker':ticker,'reason':'New amount and currency require unit verification','amount':str(amount),'currency':currency})
   except (ValueError,TypeError): pass
  after={k:row.get(k) for k in before}
  if after!=before:
   row['source']='https://eodhd.com/api/div/'+symbol
   row['dataStatus']='EODHD provider data — verify issuer announcement'
   report['changed'].append({'ticker':ticker,'symbol':symbol,'before':before,'after':after})
 # Move cursor only by number actually attempted; avoid skipping when quota exceeded.
 attempted=len(report['checked'])+len(report['errors'])
 state={'offset':(offset+attempted)%max(1,len(candidates)),'mapped_instruments':len(candidates),'daily_request_cap':LIMIT}
 STATE.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n')
 REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
 if report['changed']: DATA.write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print('EODHD checked',len(report['checked']),'changed',len(report['changed']),'reviews',len(report['review']),'errors',len(report['errors']),'mapped',len(candidates))
 for r in report['changed']: print('UPDATED',r['ticker'],r['after'])
 for r in report['errors']: print('ERROR',r['ticker'],r['error'])
 if report['errors'] and not report['checked']: raise RuntimeError('No successful EODHD requests; inspect report')

if __name__=='__main__':
 try: main()
 except Exception as exc: print('EODHD sync failed:',str(exc),file=sys.stderr);sys.exit(1)
