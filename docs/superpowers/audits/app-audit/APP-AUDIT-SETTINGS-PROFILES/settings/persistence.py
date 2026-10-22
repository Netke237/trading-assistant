"""Isolated minimal FastAPI routers. Run with backend/.venv/bin/python from root.
A parent launches fresh worker processes for write and restart readback. No app.main,
scheduler startup, live services or real credentials. All mutations target a TemporaryDirectory.
"""
import hashlib,json,os,pathlib,subprocess,sys,tempfile
ROOT=pathlib.Path(__file__).resolve().parents[6]
OUT=pathlib.Path(__file__).parent

def worker(base,mode):
    assert sys.version_info[:2]==(3,11)
    base=pathlib.Path(base).resolve();assert str(base).startswith('/tmp/')
    os.environ['DATABASE_URL']='sqlite+aiosqlite:///'+str(base/'isolated.db')
    sys.path.insert(0,str(ROOT/'backend'))
    import yaml
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers import risk_settings as r, notification_settings as n
    from app.services import scheduling_tz as tz,portfolio_risk as pr,alert_generator as ag
    from app.routers import scan
    from app.services import config_loader,atomic_yaml
    from unittest.mock import patch
    config_loader._CONFIG_DIR=base
    r._RISK_PATH=base/'risk_rules.yaml';r._SETTINGS_PATH=base/'settings.yaml';n._SETTINGS_PATH=r._SETTINGS_PATH
    tz._SETTINGS_PATH=r._SETTINGS_PATH;tz._SETTINGS_EXAMPLE_PATH=base/'missing.yaml'
    pr.CONFIG_PATH=r._RISK_PATH;ag._CONFIG_PATH=r._RISK_PATH
    from app import database
    assert str(base) in str(database.engine.url)
    for path in (r._RISK_PATH,r._SETTINGS_PATH,n._SETTINGS_PATH,tz._SETTINGS_PATH,pr.CONFIG_PATH,ag._CONFIG_PATH): assert path.is_relative_to(base)
    app=FastAPI();app.include_router(r.router);app.include_router(n.router)
    client=TestClient(app,raise_server_exceptions=False); result={'mode':mode,'isolation':{'temporary_root':str(base),'database':str(database.engine.url),'main_imported':'app.main' in sys.modules,'schedulers_started':False},'checks':[]}
    def request(method,url,body=None):
        res=client.request(method,url,json=body) if body is not None else client.request(method,url)
        try:data=res.json()
        except Exception:data=res.text
        return {'status':res.status_code,'body':data}
    def check(id,expected,observed,ok):result['checks'].append({'id':id,'expected':expected,'observed':observed,'status':'pass' if ok else 'fail'})
    if mode=='write':
        r._RISK_PATH.write_text(yaml.safe_dump({'portfolio':{'portfolio_value':100000,'max_loss_per_trade_pct':0.01},'reward_risk':{'premium_stop_pct':0.6}}));r._SETTINGS_PATH.write_text('{}\n')
        pr._load_config();ag._load_risk_config();scan._rr_cfg()
        good=request('POST','/settings/risk',{'premiumStopPct':0.55,'portfolioValue':125000,'maxLossPerTradePct':0,'maxSingleStockPositionPct':0,'targetT1Pct':0.2,'targetT2Pct':0.4,'targetT3Pct':0.6})
        read=request('GET','/settings/risk'); effective=pr._load_config()
        check('risk-zero-effective','zero persists and effective config agrees',{'save':good,'read':read,'effective':effective},good['status']==200 and read['body']['maxLossPerTradePct']==0 and effective['portfolio']['max_loss_per_trade_pct']==0)
        prior=r._RISK_PATH.read_bytes()
        invalids=[]
        for body in [{'premiumStopPct':0},{'premiumStopPct':None},{'portfolioValue':0},{'targetT1Pct':0.8,'targetT2Pct':0.2},{'maxConcurrentPositions':0}]:invalids.append({'request':body,'response':request('POST','/settings/risk',body)})
        check('risk-invalid-rollback','422 and byte-identical readback',invalids,all(i['response']['status']==422 for i in invalids) and r._RISK_PATH.read_bytes()==prior)
        nullsave=request('POST','/settings/risk',{'premiumStopPct':0.55,'portfolioValue':None,'maxLossPerTradePct':None});read=request('GET','/settings/risk')
        check('risk-null-absent','optional null retains prior; absent target resets defaults',{'save':nullsave,'read':read},read['body']['portfolioValue']==125000 and read['body']['maxLossPerTradePct']==0 and read['body']['targetT2Pct']==0.35)
        for url,body,key,val in [('/settings/scheduling',{'timezone':'Asia/Tokyo'},'timezone','Asia/Tokyo'),('/settings/history-retention',{'historyRetentionYears':0},'historyRetentionYears',1),('/settings/scheduled-scan-retention',{'scheduledScanRunRetentionDays':0},'scheduledScanRunRetentionDays',1)]:
            method='PUT' if url.endswith('scheduling') else 'POST';save=request(method,url,body);read=request('GET',url);check(key+'-normal-clamp','save/readback agree',{'save':save,'read':read},save['status']==200 and read['body'][key]==val)
        prior=r._SETTINGS_PATH.read_bytes();bad=request('PUT','/settings/scheduling',{'timezone':'Invalid/Zone'});check('timezone-invalid-rollback','422 byte-identical',bad,bad['status']==422 and prior==r._SETTINGS_PATH.read_bytes())
        # Inject OS replacement error at the real atomic writer boundary, preserving the same target.
        for url,body,path in [('/settings/risk',{'premiumStopPct':0.7},r._RISK_PATH),('/settings/scheduled-scan-retention',{'scheduledScanRunRetentionDays':99},r._SETTINGS_PATH)]:
            saved_bytes=path.read_bytes()
            def refuse_replace(src,dst):
                assert pathlib.Path(src).is_relative_to(base) and pathlib.Path(dst).is_relative_to(base)
                raise OSError('injected atomic replacement failure')
            with patch.object(atomic_yaml.os,'replace',side_effect=refuse_replace):failed=request('POST',url,body)
            read=request('GET',url); sidecars=[p.name for p in base.glob('*.tmp')]
            check('failed-write-'+url,'500, original file/readback intact, no sidecar',{'response':failed,'read':read,'sidecars':sidecars},failed['status']==500 and saved_bytes==path.read_bytes() and not sidecars)
        from app.schemas.stock_scan import StockScanRequest
        from pydantic import ValidationError
        invalid_payload={'universe':['SP500'],'direction':'Bullish','horizon':'Swing','strategy':'pullback_ema','pullback_tolerance_pct':0}
        try:
            StockScanRequest.model_validate(invalid_payload); errors=[]
        except ValidationError as exc:errors=exc.errors(include_url=False)
        check('strategy-zero-backend-validation','backend rejects persisted UI zero override',{'request':invalid_payload,'validation_errors':errors},any(e['loc']==('pullback_tolerance_pct',) for e in errors))
        result['final']={p:request('GET',p) for p in ['/settings/risk','/settings/scheduling','/settings/history-retention','/settings/scheduled-scan-retention']}
    else:result['final']={p:request('GET',p) for p in ['/settings/risk','/settings/scheduling','/settings/history-retention','/settings/scheduled-scan-retention']}
    result['hashes']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (r._RISK_PATH,r._SETTINGS_PATH)}
    print(json.dumps(result))

if len(sys.argv)>1:worker(sys.argv[1],sys.argv[2])
else:
    with tempfile.TemporaryDirectory(prefix='settings-audit-') as base:
        runs=[]
        for mode in ['write','restart-readback']:
            res=subprocess.run([sys.executable,__file__,base,mode],cwd=ROOT,text=True,capture_output=True,check=True);runs.append(json.loads(res.stdout))
        out={'python':sys.version,'source_sha':'880c8441841cc22d5090cdc5f984e4cf7e3d9a8d','runs':runs,'restart_readback_identical':runs[0]['final']==runs[1]['final'],'restart_hashes_identical':runs[0]['hashes']==runs[1]['hashes']}
        (OUT/'persistence-output.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2))
