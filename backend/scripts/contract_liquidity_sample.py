"""Sample option-chain liquidity (volume / OI / spread) by DTE window for names from the last
options scan. Needs the backend on :8000. Writes liq_sample.json in the cwd.
Used by docs/superpowers/plans/2026-09-30-contract-liquidity-dte-plan.md section 2."""
import json,random,asyncio,httpx,time,os
d=httpx.get("http://localhost:8000/api/scan/last",timeout=30).json()
syms=sorted({x['symbol'] for x in d['rejected'] if x['reason'].startswith(('contracts rejected','Score gate'))}|{c['symbol'] for c in d['candidates']})
random.seed(7); sample=sorted(random.sample(syms,min(60,len(syms))))
buckets={'swing':(5,15),'position':(15,45),'quarterly':(45,60),'semiannual':(98,105)}
out=[]
async def one(cl,sem,s,b,h):
    async with sem:
        u=f"http://localhost:8000/api/contracts?symbol={s}&right=C&stock_score=70&direction=Bullish&horizon=Position&limit=100&max_price=500&hold_min_days={h[0]}&hold_max_days={h[1]}"
        try:
            r=await cl.get(u,timeout=90); rows=r.json() if r.status_code==200 else []
        except Exception as e: rows=[]; print('err',s,b,e)
        for c in rows if isinstance(rows,list) else []:
            bd=c.get('breakdown') or {}
            L=bd.get('liquidityDetail') or {}; S=bd.get('spreadDetail') or {}
            out.append(dict(sym=s,bucket=b,dte=c.get('dte'),delta=c.get('delta'),price=c.get('price'),vol=L.get('volume'),oi=L.get('open_interest'),spread_pct=S.get('spread_pct'),score=c.get('score')))
async def main():
    sem=asyncio.Semaphore(3)
    async with httpx.AsyncClient() as cl:
        await asyncio.gather(*[one(cl,sem,s,b,h) for s in sample for b,h in buckets.items()])
t=time.time(); asyncio.run(main())
json.dump({'taken_at':time.strftime('%Y-%m-%d %H:%M %Z'),'sample':sample,'rows':out},open('liq_sample.json','w'))
print('rows',len(out),'secs',int(time.time()-t))
