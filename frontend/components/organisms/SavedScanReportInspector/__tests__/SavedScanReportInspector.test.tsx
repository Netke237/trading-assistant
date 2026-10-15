import React from 'react';
import { render, screen, fireEvent, waitFor, act, within } from '@testing-library/react';
import { useScanReportUpdates } from '@/lib/scanReports';
import { useScanStore } from '@/lib/scanStore';
import { scanReportInputsDiffer, SavedScanReportInspector } from '../index';
import { api } from '@/lib/api';
jest.mock('@/lib/api', () => ({ api: { getLatestScanReport: jest.fn(), getLegacyScanReports: jest.fn() } }));
const latest = api.getLatestScanReport as jest.Mock;
const report = (category: string, id: string, generation = 1) => ({category, run_id:id, generation, trigger:'manual', started_at:'2026-10-13T01:00:00Z', ended_at:'2026-10-13T01:01:00Z', status:'complete', persistence:'saved', inputs:{request:{direction:'bullish'},effective_configuration_complete:false}, diagnostics_available:true, diagnostics:{accepted_symbols:[id],stage_counts_available:false}, result:{candidates:[{symbol:id, metrics:{atr_ratio:0}}]}});
beforeEach(() => { jest.clearAllMocks(); useScanReportUpdates.setState({revision:0,current:{}}); latest.mockImplementation((c:string) => Promise.resolve({category:c,latest_attempt:report(c, c+'-A'),previous_report:null})); });
test('all five categories are independently readable after remount and options replacement', async () => {
  const data = Object.fromEntries(['options','stocks','prebreakout','pullback','fib'].map(c => [c, report(c,c+'-A')]));
  latest.mockImplementation((c:string) => Promise.resolve({category:c,latest_attempt:data[c],previous_report:null}));
  for (const c of Object.keys(data)) { const r=render(<SavedScanReportInspector category={c as 'options'} />); await screen.findByText('Run '+c+'-A'); expect(screen.getAllByText(/atr_ratio/)[0]).toHaveTextContent('0'); r.unmount(); }
  data.options=report('options','options-F',2);
  for (const c of Object.keys(data)) { const r=render(<SavedScanReportInspector category={c as 'options'} />); await screen.findByText('Run '+data[c].run_id); expect(JSON.parse(screen.getByText(/"diagnostics":/).textContent!)).toEqual({diagnostics:data[c].diagnostics,result:data[c].result}); r.unmount(); }
  expect(latest).toHaveBeenCalledTimes(10);
});
test('late category response cannot replace selected category', async () => {
 let resolve!: (x:unknown)=>void;
 latest.mockImplementation((c:string) => c==='options' ? new Promise(r=>{resolve=r;}) : Promise.resolve({category:c,latest_attempt:report(c,'stocks-B'),previous_report:null}));
 render(<SavedScanReportInspector category="options" />);
 fireEvent.change(screen.getByLabelText('Report category'),{target:{value:'stocks'}});
 await screen.findByText('Run stocks-B'); resolve({category:'options',latest_attempt:report('options','options-A'),previous_report:null});
 await waitFor(()=>expect(screen.queryByText('Run options-A')).not.toBeInTheDocument());
});
test('failed attempt and previous evidence remain distinct, missing diagnostics never means zero', async () => {
 latest.mockResolvedValue({category:'options',latest_attempt:{...report('options','failed'),status:'failed',diagnostics_available:false,diagnostics:null},previous_report:report('options','previous')});
 render(<SavedScanReportInspector category="options" currentInputs={{direction:'bearish'}} />);
 await screen.findByText('Run failed'); expect(screen.getByText(/Diagnostics unavailable/)).toBeInTheDocument();
 fireEvent.click(screen.getByText('Previous saved report'));
 expect(screen.getByText('Run previous')).toBeInTheDocument(); expect(screen.getByText(/Current controls differ/)).toBeInTheDocument();
});
test('read failure and absent report are explicitly unavailable', async () => {
 latest.mockRejectedValue(new Error('storage')); const r=render(<SavedScanReportInspector category="fib" />);
 await screen.findByText('Saved report storage unavailable.'); r.unmount();
 latest.mockResolvedValue({category:'fib',latest_attempt:null,previous_report:null}); render(<SavedScanReportInspector category="fib" />); await screen.findByText('No saved report available.');
});

test('clearing candidates and editing controls leaves frozen report contents intact', async()=>{
 const saved=report('options','persistent'); latest.mockResolvedValue({category:'options',latest_attempt:saved,previous_report:null});
 const r=render(<SavedScanReportInspector category="options" currentInputs={{direction:'bullish'}} tableRunId="table-old" />);
 await screen.findByText('Run persistent');
 act(()=>useScanStore.setState({scanResult:null,rejectedLog:[]}));
 r.rerender(<SavedScanReportInspector category="options" currentInputs={{direction:'bearish'}} tableRunId={null} />);
 expect(screen.getByText(/Current controls differ/)).toBeInTheDocument();expect(screen.getByText(/Displayed table run: unavailable/)).toBeInTheDocument();
 expect(JSON.parse(screen.getByText(/"diagnostics":/).textContent!)).toEqual({diagnostics:saved.diagnostics,result:saved.result});
});
test('raw report and exclusion data are collapsed, and opening a different run resets disclosure', async () => {
 const saved = { ...report('options', 'compact'), diagnostics: { excluded: [{symbol:'SKIP',reason:'excluded_by_scan_policy'}] } };
 latest.mockResolvedValue({category:'options',latest_attempt:saved,previous_report:report('options','previous')});
 render(<SavedScanReportInspector category="options" />);
 await screen.findByText('Run compact');
 const raw = screen.getByText('Saved survivors, exclusions, observed diagnostics and results').closest('details')!;
 const exclusions = screen.getByText('Saved exclusions').closest('details')!;
 expect(raw.open).toBe(false); expect(exclusions.open).toBe(false);
 expect(raw.querySelector('pre')).not.toBeVisible(); expect(exclusions.querySelector('pre')).not.toBeVisible();
 fireEvent.click(within(raw).getByText('Saved survivors, exclusions, observed diagnostics and results'));
 expect(raw.open).toBe(true);
 expect(JSON.parse(raw.querySelector('pre')!.textContent!)).toEqual({diagnostics:saved.diagnostics,result:saved.result});
 fireEvent.click(screen.getByText('Previous saved report'));
 expect(screen.getByText('Run previous')).toBeInTheDocument();
 expect(screen.getByText('Saved survivors, exclusions, observed diagnostics and results').closest('details')!.open).toBe(false);
 expect(screen.getByText('View record').closest('details')!.open).toBe(false);
});
test('control removal and zero follow frozen request semantics',()=>{
 expect(scanReportInputsDiffer({min_price:20,overrides:{fast_ema:5}},{overrides:{}})).toBe(true);
 expect(scanReportInputsDiffer({min_price:0,overrides:{}},{overrides:{}})).toBe(true);
 expect(scanReportInputsDiffer({min_price:null,overrides:{fast_ema:0}},{overrides:{fast_ema:0}})).toBe(false);
 expect(scanReportInputsDiffer({overrides:{a:0,b:1}},{overrides:{b:1,a:0}})).toBe(false);
});
test('unsaved current report identifies failure separately from previous durable evidence',async()=>{
 useScanReportUpdates.getState().record('stocks',{run_id:'unsaved-new',generation:9,persistence:'unavailable',accepted_symbols:['NEW'],pipeline_counts:{scanned:1}});
 latest.mockResolvedValue({category:'stocks',latest_attempt:report('stocks','saved-old',8),previous_report:null});
 render(<SavedScanReportInspector category="stocks" />);await screen.findByText('Run saved-old');
 expect(screen.getByText(/Current run unsaved-new: report unsaved/)).toBeInTheDocument();expect(screen.queryByText('Run unsaved-new')).not.toBeInTheDocument();
});
test('legacy evidence is accessible without inventing a category or diagnostics',async()=>{
 const entry={run_id:'legacy:1',category:'legacy/unclassified',status:'complete',inputs:null,result:{candidates:[{symbol:'OLD',score:0}]}};
 (api.getLegacyScanReports as jest.Mock).mockResolvedValue([entry]);render(<SavedScanReportInspector category="fib" />);await screen.findByText('Run fib-A');
 fireEvent.change(screen.getByLabelText('Report category'),{target:{value:'legacy'}});
 await screen.findByText(/Legacy \/ unclassified evidence/);expect(JSON.parse(screen.getByText(/"legacy:1"/).textContent!)).toEqual(entry);expect(latest).toHaveBeenCalledTimes(1);
});
test('same category stale reads cannot replace higher server generation',async()=>{
 let resolve!:(value:unknown)=>void;latest.mockResolvedValueOnce({category:'options',latest_attempt:report('options','newest',10),previous_report:null}).mockImplementationOnce(()=>new Promise(r=>{resolve=r;}));
 render(<SavedScanReportInspector category="options" />);await screen.findByText('Run newest');fireEvent.click(screen.getByText('Refresh report'));
 await waitFor(()=>expect(latest).toHaveBeenCalledTimes(2));resolve({category:'options',latest_attempt:report('options','older',9),previous_report:null});await screen.findByText('Run newest');expect(screen.queryByText('Run older')).not.toBeInTheDocument();
});
test('terminal report cannot regress to a running snapshot of the same generation',async()=>{
 latest.mockResolvedValueOnce({category:'stocks',latest_attempt:report('stocks','terminal',6),previous_report:null}).mockResolvedValueOnce({category:'stocks',latest_attempt:{...report('stocks','terminal',6),status:'running',diagnostics_available:false,diagnostics:null},previous_report:null});
 render(<SavedScanReportInspector category="stocks" />);await screen.findByText('Run terminal');fireEvent.click(screen.getByText('Refresh report'));await screen.findByText('Saved accepted results');expect(screen.getByText(/stocks · complete/)).toBeInTheDocument();
});
test('unmount aborts retrieval and category lookup does not change scan navigation',async()=>{
 let resolve!:(value:unknown)=>void;latest.mockImplementation(()=>new Promise(r=>{resolve=r;}));
 const mode=useScanStore.getState().screenerMode;const r=render(<SavedScanReportInspector category="options" />);
 await waitFor(()=>expect(latest).toHaveBeenCalledTimes(1));const signal=latest.mock.calls[0][1] as AbortSignal;
 r.unmount();expect(signal.aborted).toBe(true);await act(async()=>resolve({category:'options',latest_attempt:report('options','ignored'),previous_report:null}));expect(useScanStore.getState().screenerMode).toBe(mode);
});
test('drawer contains keyboard focus and restores opener when closed',async()=>{
 const close=jest.fn();const r=render(<><button>Open report</button><SavedScanReportInspector category="fib" isDrawer isOpen={false} onClose={close}/></>);
 const opener=screen.getByText('Open report');opener.focus();r.rerender(<><button>Open report</button><SavedScanReportInspector category="fib" isDrawer isOpen onClose={close}/></>);
 await screen.findByText('Run fib-A');const drawer=screen.getByRole('dialog',{name:'Saved scan report'});
 const controls=drawer.querySelectorAll<HTMLElement>('button:not([disabled]),select,input,summary,a[href]');const first=controls[0],last=controls[controls.length-1];
 expect(first).toHaveFocus();fireEvent.keyDown(window,{key:'Tab',shiftKey:true});expect(last).toHaveFocus();fireEvent.keyDown(window,{key:'Tab'});expect(first).toHaveFocus();fireEvent.keyDown(window,{key:'Escape'});expect(close).toHaveBeenCalledTimes(1);
 r.rerender(<><button>Open report</button><SavedScanReportInspector category="fib" isDrawer isOpen={false} onClose={close}/></>);expect(opener).toHaveFocus();
});
test.each([['stocks',null],['stocks',{enabled:true}],['options',null],['options',{enabled:true}]] as const)('invalid %s settings make controls comparison unavailable while saved evidence stays readable',async(category,gate)=>{
 const { useSettingsStore } = await import('@/lib/settingsStore');
 const original=useSettingsStore.getState().confidenceGate;
 useSettingsStore.setState({confidenceGate:gate as never});
 try {
  const r=render(<SavedScanReportInspector category={category} />);
  await screen.findByText('Run '+category+'-A');
  expect(screen.getByText(/Current controls comparison unavailable/)).toBeInTheDocument();
  expect(JSON.parse(screen.getByText(/"diagnostics":/).textContent!)).toEqual({diagnostics:report(category,category+'-A').diagnostics,result:report(category,category+'-A').result});
  expect(useSettingsStore.getState().confidenceGate).toBe(gate);r.unmount();
 } finally { act(()=>useSettingsStore.setState({confidenceGate:original})); }
});
