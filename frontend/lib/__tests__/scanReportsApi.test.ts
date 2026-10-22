import { api, API_BASE_URL } from '../api';
import { useScanReportUpdates } from '../scanReports';
const request = {universe:['AAPL'],direction:'Bullish',horizon:'Swing',strategy:'pullback_ema'};
const response = (value:unknown,id:string,generation:number,persistence='saved') => ({ok:true,json:async()=>value,headers:{get:(name:string)=>({'X-Scan-Report-Run-Id':id,'X-Scan-Report-Generation':String(generation),'X-Scan-Report-Persistence':persistence}[name]??null)}});
beforeEach(()=>{useScanReportUpdates.setState({revision:0,current:{}});global.fetch=jest.fn();});
test('system retrieval uses read-only category and immutable run endpoints and returns exact contents',async()=>{
 const envelope={category:'fib',latest_attempt:{run_id:'fib-E',generation:1,result:{candidates:[{symbol:'AAPL',confidence:0}]}},previous_report:null};
 (fetch as jest.Mock).mockResolvedValue({ok:true,json:async()=>envelope});
 expect(await api.getLatestScanReport('fib')).toEqual(envelope);
 expect(fetch).toHaveBeenLastCalledWith(API_BASE_URL+'/api/scan-reports/latest/fib',{signal:undefined});
 await api.getScanReport('immutable-id');expect(fetch).toHaveBeenLastCalledWith(API_BASE_URL+'/api/scan-reports/runs/immutable-id',{signal:undefined});
 await api.getLegacyScanReports();expect(fetch).toHaveBeenLastCalledWith(API_BASE_URL+'/api/scan-reports/legacy',{signal:undefined});
 expect((fetch as jest.Mock).mock.calls.every(call=>!call[1].method)).toBe(true);
});
test('array callers retain arrays while headers carry category-local metadata',async()=>{
 const rows=[{symbol:'AAPL',confidence:0,metrics:{atr_ratio:0}}];const cb=jest.fn();
 (fetch as jest.Mock).mockResolvedValue(response(rows,'pb-C',3,'unavailable'));
 expect(await api.prebreakoutScan(['AAPL'],'Bullish',{},undefined,cb)).toEqual(rows);
 expect(cb).toHaveBeenCalledWith(expect.objectContaining({run_id:'pb-C',generation:3,persistence:'unavailable',accepted_symbols:['AAPL']}));
 expect(useScanReportUpdates.getState().current.prebreakout?.run_id).toBe('pb-C');
 expect(useScanReportUpdates.getState().current.stocks).toBeUndefined();
});
test('explicit Pullback dispatch and reversed completion retain newest server generation per category',async()=>{
 let older!: (v:unknown)=>void;
 (fetch as jest.Mock).mockImplementationOnce(()=>new Promise(r=>{older=r;})).mockResolvedValueOnce(response({candidates:[],report_run_id:'D-new',report_generation:8,report_persistence:'saved'},'D-new',8));
 const first=api.postStockScan({...request,category:'pullback'});await api.postStockScan({...request,category:'pullback'});
 older(response({candidates:[{symbol:'AAPL'}],report_run_id:'D-old',report_generation:7,report_persistence:'saved'},'D-old',7));await first;
 expect(useScanReportUpdates.getState().current.pullback?.run_id).toBe('D-new');expect(useScanReportUpdates.getState().current.stocks).toBeUndefined();
 expect(JSON.parse((fetch as jest.Mock).mock.calls[0][1].body).category).toBe('pullback');
});
test('save failure metadata never retains arbitrary raw request/result or provider text',async()=>{
 (fetch as jest.Mock).mockResolvedValue(response({candidates:[{symbol:'AAPL',credentials:'secret'}],pipeline:{scanned:1,failed_data:0,provider_error:'secret'},report_run_id:'unsaved',report_generation:5,report_persistence:'unavailable'},'unsaved',5));
 await api.postStockScan(request);
 expect(useScanReportUpdates.getState().current.stocks).toEqual({run_id:'unsaved',generation:5,persistence:'unavailable',accepted_symbols:['AAPL'],pipeline_counts:{scanned:1,failed_data:0}});
});
test('category is captured before awaiting transport even if caller mutates request object',async()=>{
 let resolve!:(value:unknown)=>void;(fetch as jest.Mock).mockImplementation(()=>new Promise(r=>{resolve=r;}));
 const mutable={...request,category:'pullback' as 'pullback'|'stocks'};const pending=api.postStockScan(mutable);mutable.category='stocks';
 resolve(response({candidates:[]},'captured-D',4));await pending;
 expect(useScanReportUpdates.getState().current.pullback?.run_id).toBe('captured-D');expect(useScanReportUpdates.getState().current.stocks).toBeUndefined();
});
test('missing server generation remains unavailable rather than becoming invented zero',async()=>{
 (fetch as jest.Mock).mockResolvedValue({ok:true,json:async()=>[],headers:{get:(name:string)=>name==='X-Scan-Report-Run-Id'?'missing-generation':null}});
 await api.fibPullbackScan([],'Bullish');expect(useScanReportUpdates.getState().current.fib).toBeUndefined();
});
