"""Evidence only. Python 3.11; all broker traffic, worker scheduling and DB calls mocked.
Run from repository root:
  backend/.venv/bin/python docs/superpowers/measurements/broker-path-residuals/broker_error_probe.py
This reproduces current behavior, not assertions of desired policy.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / 'backend'))
assert sys.version_info[:2] == (3, 11), 'Python 3.11 required'
import os, asyncio
from unittest.mock import patch, MagicMock
os.environ['DATABASE_URL']='sqlite+aiosqlite:////tmp/broker-evidence-db.sqlite'
os.environ['BAMENDJOU_CREDS_PATH']='/tmp/broker-evidence-creds.yaml'
import httpx
from app.data.alpaca_paper_execution import AlpacaPaperAdapter
from app.data.ibkr_paper import BrokerOrder, OrderResult, IbkrPaperAdapter
from app.routers import broker as routes
from fastapi import HTTPException
order=BrokerOrder('AAPL','SELL','CLOSE',1,'LMT',150)
async def immediate_worker(fn,*args): return fn(*args)
async def manual_cases():
    req=routes.StockOrderRequest(broker='alpaca_paper',symbol='AAPL',action='SELL',effect='CLOSE',quantity=1,limit_price=150)
    adapter=AlpacaPaperAdapter('mock-key','mock-secret')
    router=MagicMock(); router.resolve.return_value=adapter
    for name, response in [('invalid-json',httpx.Response(200,content=b'{bad')),('json-list',httpx.Response(200,json=[])),('empty-object',httpx.Response(200,json={})),('broker-422',httpx.Response(422,json={'message':'invalid order'}))]:
        routes._idempotency_cache.clear(); routes._idempotency_inflight.clear()
        with patch.object(routes,'build_router_from_credentials',return_value=router), patch.object(routes,'log_event') as log, patch.object(routes.asyncio,'to_thread',side_effect=immediate_worker), patch('app.data.alpaca_paper_execution.httpx.post',return_value=response) as post:
            try: result=await asyncio.wait_for(routes.place_stock_order(req),2); result=f'returned {result}'
            except HTTPException as e: result=f'HTTP {e.status_code}: {e.detail}'
            except Exception as e: result=f'unhandled {type(e).__name__}: {e}'
            print(name,result,'POSTS',post.call_count,'EVENTS',[c.args[0] for c in log.call_args_list])
    routes._idempotency_cache.clear(); routes._idempotency_inflight.clear()
    entered=asyncio.Event(); release=asyncio.Event(); count=[0]
    async def mock_worker(fn,*args):
        count[0]+=1
        if count[0]==1:
            entered.set(); await release.wait()
            raise RuntimeError('broker accepted but reply timed out')
        return OrderResult('SECOND-ORDER','accepted','alpaca_paper')
    async def capture():
        try: return await routes.place_stock_order(req)
        except HTTPException as e: return {'http':e.status_code,'detail':e.detail}
    with patch.object(routes,'build_router_from_credentials',return_value=router),patch.object(routes,'log_event'),patch.object(routes.asyncio,'to_thread',side_effect=mock_worker):
        first=asyncio.create_task(capture()); await entered.wait()
        second=asyncio.create_task(capture()); await asyncio.sleep(.01); release.set()
        print('concurrent-uncertain',await asyncio.gather(first,second),'DISPATCHES',count[0])
async def orphan_case():
    from unittest.mock import AsyncMock
    from app.models.audit_event import AuditEventModel
    from app.services.audit import log_approval
    from app.routers.portfolio import delete_position
    positions={'REC-MOCK':object()}; approvals=[]
    # The position writer committed; a second mocked DB session deletes it
    # before the original request reaches log_approval's separate commit.
    db=MagicMock()
    result=MagicMock(); result.scalar_one_or_none.return_value=positions['REC-MOCK']
    async def execute(statement):
        if str(statement).startswith('DELETE'): approvals.clear()
        return result
    async def delete(position): positions.clear()
    db.execute=AsyncMock(side_effect=execute); db.delete=AsyncMock(side_effect=delete); db.commit=AsyncMock()
    db.add.side_effect=approvals.append
    await delete_position('REC-MOCK',db)
    with patch('app.services.audit.log_event') as log: await log_approval('REC-MOCK',{'entryPrice':150},db)
    print('delete-before-approval','positions',len(positions),'approvals',len(approvals),'JSONL_EVENTS',log.call_count)

def adapter_cases():
    from app.data.tradier_paper import TradierPaperAdapter
    from app.data.tastytrade_paper import TastytradePaperAdapter
    from unittest.mock import AsyncMock
    adapters=[('alpaca',AlpacaPaperAdapter('mock','mock')),('ibkr',IbkrPaperAdapter('http://mock','mock')),('tradier',TradierPaperAdapter('mock','mock'))]
    for name,adapter in adapters:
        with patch('httpx.post',return_value=httpx.Response(200,content=b'{bad')) as post, patch('app.data.ibkr_paper.paper_gateway_available',return_value=True),patch('app.data.governor.get_governor') as governor:
            governor.return_value.admit_sync.return_value=True
            try: adapter.place_order(order)
            except Exception as e: print(name,'invalid-json',type(e).__name__,'POSTS',post.call_count)
    async def tasty():
        adapter=TastytradePaperAdapter('mock'); account=MagicMock(); account.place_order=AsyncMock(return_value=None)
        with patch('app.data.tastytrade_paper.get_session',return_value=object()), patch('app.data.tastytrade_paper.Account.get',new=AsyncMock(return_value=account)),patch.object(adapter,'_resolve_leg',new=AsyncMock(return_value=MagicMock())),patch('app.data.tastytrade_paper.LimitOrder',return_value=object()):
            try: await adapter._place_order_async(order)
            except Exception as e: print('tastytrade','missing SDK response',type(e).__name__,'SUBMISSIONS',account.place_order.await_count)
    asyncio.run(tasty())
async def main(): await manual_cases(); await orphan_case()
if __name__=='__main__':
    adapter_cases()
    asyncio.run(main())
