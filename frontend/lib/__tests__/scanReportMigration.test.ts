import { useScanStore } from '../scanStore';
const options=useScanStore.persist.getOptions();
test('v19 preserves every legacy result and evidence with unavailable report identities, never guesses a category',()=>{
 expect(options.version).toBeGreaterThanOrEqual(19);
 const legacy={scan_id:'old',candidates:[],rejected:[{symbol:'AAPL',reason:'measured 0'}],pipeline:{scanned:1,failed_score:1}};
 const blob={scanResult:legacy,previousRun:legacy,stockScanResult:legacy,previousStockScanResult:legacy,context:{direction:'Bearish'},unrelated:'keep'};
 const out=options.migrate!(blob,18) as unknown as typeof blob;
 for(const key of ['scanResult','previousRun','stockScanResult','previousStockScanResult'] as const)expect(out[key]).toEqual({...legacy,report_run_id:null,report_generation:null,report_persistence:null});
 expect(out.context).toEqual(blob.context);expect(out.unrelated).toBe('keep');
 expect(options.name).toBe('bamendjou-scan-store');
});
