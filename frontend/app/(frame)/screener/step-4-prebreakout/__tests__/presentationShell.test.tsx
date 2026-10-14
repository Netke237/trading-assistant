import { render, screen, fireEvent, act } from '@testing-library/react';
import Page from '../page';
import {scanSnapshot} from '../scanThresholds';
import { api } from '@/lib/api';
import { useScanStore } from '@/lib/scanStore';
import { useUniverseStore } from '@/lib/universeStore';
jest.mock('@/lib/api',()=>({api:{getLatestScanReport:jest.fn(()=>Promise.resolve({category:'prebreakout',latest_attempt:null,previous_report:null})),prebreakoutScan:jest.fn(),fibPullbackScan:jest.fn(),postStockScan:jest.fn()}}));
jest.mock('@/components/organisms/SavedScanReportInspector',()=>({SavedScanReportInspector:()=>null}));
jest.mock('@/components/organisms/CompositeAlertDialog',()=>({CompositeAlertDialog:()=>null}));
const row=(symbol:string,confidence=80)=>({symbol,direction:'Bullish',confidence,metrics:{atr_ratio:0.6}});
beforeEach(()=>{jest.clearAllMocks();useUniverseStore.setState({pick:'SP500'});useScanStore.setState({context:null,preBreakoutResults:[],fibPullbackResults:[]});});
test('shell remains available without candidates and keyboard selection follows symbol across refresh',async()=>{
 useScanStore.setState({preBreakoutResults:[row('AAA'),row('BBB',70)]}); render(<Page/>);
 expect(screen.getByRole('region',{name:'Selected setup chart'})).toBeInTheDocument();
 fireEvent.keyDown(screen.getByRole('button',{name:'Select BBB'}),{key:'Enter'});
 expect(screen.getByLabelText('Selected setup')).toHaveTextContent('BBB');
 act(()=>useScanStore.setState({preBreakoutResults:[row('BBB',90),row('AAA',60)]}));
 expect(screen.getByLabelText('Selected setup')).toHaveTextContent('BBB');
 act(()=>useScanStore.setState({preBreakoutResults:[]}));
 expect(screen.getByLabelText('Selected setup')).toHaveTextContent('Select a candidate');
});
test('late candidate replies after parameter invalidation are ignored',async()=>{
 let resolve!:(x:unknown)=>void;(api.prebreakoutScan as jest.Mock).mockImplementation(()=>new Promise(r=>{resolve=r;}));render(<Page/>);
 fireEvent.click(screen.getByRole('button',{name:'Run Scan'}));
 fireEvent.change(screen.getAllByRole('spinbutton')[0],{target:{value:'0.875'}});
 await act(async()=>resolve([row('LATE')]));expect(useScanStore.getState().preBreakoutResults).toEqual([]);
});
test('off-step proximity input displays its exact typed percentage',()=>{render(<Page/>);const input=screen.getAllByRole('spinbutton')[5];fireEvent.change(input,{target:{value:'7.25'}});expect(input).toHaveValue(7.25);});
test('successful row snapshots retain exact thresholds across remount and are unavailable on replacement arrays',async()=>{
 (api.prebreakoutScan as jest.Mock).mockResolvedValue([row('SCANNED')]);const view=render(<Page/>);
 fireEvent.change(screen.getAllByRole('spinbutton')[0],{target:{value:'0.875'}});
 fireEvent.change(screen.getAllByRole('spinbutton')[1],{target:{value:'23.9'}});
 fireEvent.change(screen.getAllByRole('spinbutton')[5],{target:{value:'7.25'}});
 await act(async()=>fireEvent.click(screen.getByRole('button',{name:'Run Scan'})));
 expect(screen.getByTitle(/23-bar average ATR/)).toHaveAttribute('title',expect.stringContaining('0.875'));
 view.unmount();render(<Page/>);
 expect(screen.getByTitle(/23-bar average ATR/)).toHaveAttribute('title',expect.stringContaining('0.875'));
 expect(screen.getByText(/within 7.25%/)).toBeInTheDocument();
 act(()=>useScanStore.setState({preBreakoutResults:[row('LEGACY')]}));
 expect(screen.getByTitle(/unknown-bar average ATR/)).toHaveAttribute('title',expect.stringContaining('scan snapshot unknown'));
});
test('mode and horizon changes supersede pending replies without clearing completed tables',async()=>{
 let resolve!:(x:unknown)=>void;(api.prebreakoutScan as jest.Mock).mockImplementation(()=>new Promise(r=>{resolve=r;}));
 useScanStore.setState({preBreakoutResults:[row('PRIOR')]});render(<Page/>);fireEvent.click(screen.getByRole('button',{name:'Run Scan'}));
 fireEvent.click(screen.getByRole('button',{name:'Fib Pullback'}));
 await act(async()=>resolve([row('LATE')]));expect(useScanStore.getState().preBreakoutResults[0].symbol).toBe('PRIOR');
 fireEvent.click(screen.getByRole('button',{name:'Pre-Breakout'}));fireEvent.click(screen.getByRole('button',{name:'Run Scan'}));
 act(()=>useScanStore.setState({context:{direction:'Bullish',horizon:'Position'} as never}));
 await act(async()=>resolve([row('OTHER')]));expect(useScanStore.getState().preBreakoutResults[0].symbol).toBe('PRIOR');
});
test('scan errors retain candidates and the chart shell',async()=>{
 useScanStore.setState({preBreakoutResults:[row('PRIOR')]});(api.prebreakoutScan as jest.Mock).mockRejectedValue(new Error('Scan failed'));
 render(<Page/>);await act(async()=>fireEvent.click(screen.getByRole('button',{name:'Run Scan'})));
 expect(screen.getByText('Scan failed')).toBeInTheDocument();expect(screen.getByRole('button',{name:'Select PRIOR'})).toBeInTheDocument();expect(screen.getByRole('region',{name:'Selected setup chart'})).toBeInTheDocument();
});
test('Fib off-step tolerance is retained in the panel',()=>{render(<Page/>);fireEvent.click(screen.getByRole('button',{name:'Fib Pullback'}));const input=screen.getAllByRole('spinbutton')[1];fireEvent.change(input,{target:{value:'1.55'}});expect(input).toHaveValue(1.55);});
test('late metadata and rows never relabel a newer table snapshot',async()=>{
 const pending:Array<{resolve:(rows:unknown)=>void; metadata:(value:{run_id:string})=>void}>=[];
 (api.prebreakoutScan as jest.Mock).mockImplementation((_s,_d,_p,_u,metadata)=>new Promise(resolve=>pending.push({resolve,metadata})));
 render(<Page/>);fireEvent.click(screen.getByRole('button',{name:'Run Scan'}));
 fireEvent.change(screen.getAllByRole('spinbutton')[0],{target:{value:'0.875'}});fireEvent.click(screen.getByRole('button',{name:'Run Scan'}));
 await act(async()=>{pending[1].metadata({run_id:'NEW'});pending[1].resolve([row('NEW')]);});
 await act(async()=>{pending[0].metadata({run_id:'OLD'});pending[0].resolve([row('OLD')]);});
 expect(useScanStore.getState().preBreakoutResults[0].symbol).toBe('NEW');
 expect(scanSnapshot(useScanStore.getState().preBreakoutResults)?.scope.runId).toBe('NEW');
});
test('root container carries the integrated presentation v2 marker in every sub-mode',()=>{
 const {container}=render(<Page/>);const root=container.firstElementChild;
 for(const name of ['Pre-Breakout',/^Pullback to EMA/,'Fib Pullback']){
  fireEvent.click(screen.getByRole('button',{name}));
  expect(screen.getByRole('button',{name})).toHaveAttribute('aria-pressed','true');
  expect(container.firstElementChild).toBe(root);
  expect(root).toHaveAttribute('data-presentation','prebreakout-v2');
 }
});
