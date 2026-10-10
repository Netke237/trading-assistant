from pathlib import Path
import subprocess, json, hashlib, sys
root=Path.cwd()
python=Path('C:/GitHub/trading-assistant/backend/.venv/Scripts/python.exe')
page='frontend/app/(frame)/screener/step-7-trade-card/page.tsx'
auto='backend/app/services/auto_trader.py'
block='''        _qs = _option_quote_state(_option_symbol)
        if _qs != "live":
            logger.warning("No live option quote for %s (%s) — armed state preserved", _option_symbol, _qs)
            raise ArmPreservedError(
                f"No live option quote for {_option_symbol} ({_qs}) "
                "— armed state preserved for retry"
            )

'''
frontend_cmd=['node', 'node_modules/jest/bin/jest.js', '--runInBand', '--runTestsByPath', 'app/(frame)/screener/step-7-trade-card/__tests__/no-live-quote.test.tsx', '--silent']
backend_cmd=[str(python),'-m','pytest','tests/test_no_live_quote_fire_gate.py','-q','--tb=short']
mutations={
'M7':(auto,block,'',backend_cmd,'backend'),
'M8':(auto,block,'',backend_cmd,'backend'),
'M9':(page,'spread:      q?.spread ?? liveQcd.spread!','spread:      q?.spread ?? 0',frontend_cmd,'frontend'),
'M12':(page,'freshQuote?.quoteLive !== true && quoteConfirmation?.contractKey !== keyAtSend','false',frontend_cmd,'frontend'),
'M13':(page,'freshQuote = await api.getContractQuote(card.symbol, cdAtSend.strike, cdAtSend.expiry, cdAtSend.right, quoteController.signal).catch(() => null);','freshQuote = liveQuoteForCard;',frontend_cmd,'frontend'),
'M14':(page,'freshQuote?.quoteLive !== true && quoteConfirmation?.contractKey !== keyAtSend','freshQuote?.quoteLive !== true && !quoteConfirmation',frontend_cmd,'frontend'),
}
results=[]
for name in sys.argv[1:]:
    rel,old,new,cmd,cwd=mutations[name]
    target=root/rel
    original=target.read_bytes()
    source=original.decode('utf-8', errors='surrogateescape').replace('\r\n', '\n')
    assert source.count(old)==1,(name,source.count(old))
    modified=source.replace(old,new)
    if name=='M14':
        modified=modified.replace('  useEffect(() => { setQuoteConfirmation(null); }, [contractKey]);', '')
    if name=='M8':
        anchor='        # Defensive for an arm created before deploy or by a direct constructor.\n'
        start=modified.index('    def fire(')
        pos=modified.index(anchor,start)
        modified=modified[:pos]+block+modified[pos:]
    try:
        target.write_bytes(modified.encode('utf-8', errors='surrogateescape'))
        proc=subprocess.run(cmd,cwd=root/cwd,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=240)
        (root/f'.scratch/no-live-quote/{name}-mutation.log').write_text(proc.stdout+proc.stderr,encoding='utf-8')
        result={'mutation':name,'exit_code':proc.returncode,'log':f'.scratch/no-live-quote/{name}-mutation.log','expected_test_failed':proc.returncode==1 and ('FAILED' in proc.stdout or 'FAIL ' in proc.stderr),'original_sha256':hashlib.sha256(original).hexdigest()}
    finally:
        target.write_bytes(original)
        assert target.read_bytes()==original
    results.append(result)
    print(json.dumps(result),flush=True)
    (root/'.scratch/no-live-quote'/('mutations-'+sys.argv[1]+'.json')).write_text(json.dumps(results,indent=2)+'\n',encoding='utf-8')




