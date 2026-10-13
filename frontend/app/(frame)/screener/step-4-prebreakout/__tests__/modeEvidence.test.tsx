import { render, screen, fireEvent, act, within } from '@testing-library/react';
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
test('selected Pre evidence retains raw components, zero, null and optional Fib swing',()=>{
 const evidence={symbol:'ZERO',direction:'Bearish',confidence:0,metrics:{atr_ratio:0,range_ratio:0,vol_ratio:0,proximity_pct:0,current_atr:0,fib_dist_pct:null,extra_metric:17},confidence_breakdown:{fib_used:true,weights:{atr:.24,vol:.2,proximity:.36,fib:.2},components:{atr:{score:0,weight:.24,contribution:0}},unrounded:0.123456,confidence:0},fib_swing:{low:0,high:120}};
 useScanStore.setState({preBreakoutResults:[evidence as never]});render(<Page/>);fireEvent.click(screen.getByRole('button',{name:'Select ZERO'}));
 expect(screen.getByRole('region',{name:'Evidence for ZERO'})).toHaveTextContent('0.123456');
 expect(screen.getByText('extra_metric').parentElement).toHaveTextContent('17');
 expect(screen.getByText('fib_dist_pct').parentElement).toHaveTextContent('null');
 expect(screen.getByText(/Raw score 0/)).toHaveTextContent('Contribution 0');
 expect(screen.getByText(/Swing low/)).toHaveTextContent('$0.00');
 expect(screen.getByTitle(/Setup quality/)).toHaveAttribute('title',expect.stringContaining('24%'));
});
test('legacy disclosure says unavailable and identity groups company and actions',()=>{
 useScanStore.setState({preBreakoutResults:[row('OLD',0)]});render(<Page/>);fireEvent.click(screen.getByRole('button',{name:'Select OLD'}));
 expect(screen.getByRole('region',{name:'Evidence for OLD'})).toHaveTextContent('Confidence breakdown unavailable');
 const identity=screen.getByLabelText('Identity for OLD');expect(identity).toHaveTextContent('Company unavailable');
 expect(identity.querySelectorAll('button')).toHaveLength(2);
 expect(screen.getByRole('button',{name:'Open OLD chart in a new tab'})).toBeInTheDocument();
});
test('Fib string percent appears once and swing and zero distance survive',()=>{
 useScanStore.setState({fibPullbackResults:[{symbol:'FIB',direction:'Bearish',fib_level_hit:'61.8%',fib_dist_pct:0,at_level:true,confidence:0,fib_swing:{low:0,high:100}}]});render(<Page/>);fireEvent.click(screen.getByRole('button',{name:'Fib Pullback'}));
 expect(within(screen.getByRole('button',{name:'Select FIB'})).getByText('61.8%')).toBeInTheDocument();expect(screen.queryByText('61.8%%')).toBeNull();
 fireEvent.click(screen.getByRole('button',{name:'Select FIB'}));expect(screen.getByRole('region',{name:'Evidence for FIB'})).toHaveTextContent('Swing high $100.00');
});
test('Pullback retains authoritative conditional evidence and clicked chart identity',async()=>{
 (api.postStockScan as jest.Mock).mockResolvedValue({candidates:[{symbol:'PB',company:'Actual Company',direction:'Bearish',stock_score:0,price:0,confidence:null,status:'REJECT',confidence_qualification:'Unvalidated',stop:null,custom_evidence:{observed:0}}]});
 const open=jest.spyOn(window,'open').mockImplementation(()=>null);render(<Page/>);fireEvent.click(screen.getByRole('button',{name:'Pullback to EMA 50'}));await act(async()=>fireEvent.click(screen.getByRole('button',{name:'Run Scan'})));
 fireEvent.click(screen.getByRole('button',{name:'Open PB chart in a new tab'}));expect(open).toHaveBeenCalledWith('/chart?symbol=PB','_blank');
 fireEvent.click(screen.getByRole('button',{name:'Select PB'}));expect(screen.getByRole('region',{name:'Evidence for PB'})).toHaveTextContent('Unvalidated');expect(screen.getByText('custom_evidence').parentElement).toHaveTextContent('0');open.mockRestore();
});

test('mode tables preserve Pre confidence ordering and source Fib ordering, with zero separate from missing',()=>{
 useScanStore.setState({preBreakoutResults:[{symbol:'MISSING',direction:'Bullish',confidence:10,metrics:{}},{symbol:'ZERO',direction:'Bearish',confidence:90,metrics:{atr_ratio:0,vol_ratio:0,proximity_pct:0}}],fibPullbackResults:[{symbol:'FIRST',direction:'Bullish',fib_level_hit:'38.2',fib_dist_pct:0,at_level:true,confidence:0},{symbol:'LAST',direction:'Bearish',fib_level_hit:'61.8',fib_dist_pct:null,at_level:false,confidence:99}]});
 render(<Page/>);expect(screen.getAllByRole('button',{name:/^Select /}).map(e=>e.getAttribute('aria-label'))).toEqual(['Select ZERO','Select MISSING']);
 expect(within(screen.getByRole('button',{name:'Select ZERO'})).getAllByText('0.00')).toHaveLength(2);
 expect(within(screen.getByRole('button',{name:'Select MISSING'})).getAllByText('—')).toHaveLength(3);
 fireEvent.click(screen.getByRole('button',{name:'Fib Pullback'}));expect(screen.getAllByRole('button',{name:/^Select /}).map(e=>e.getAttribute('aria-label'))).toEqual(['Select FIRST','Select LAST']);
 expect(within(screen.getByRole('button',{name:'Select FIRST'})).getByText('0.0%')).toBeInTheDocument();expect(within(screen.getByRole('button',{name:'Select LAST'})).getByText('—')).toBeInTheDocument();
});
test('Fib tolerance uses applied fractional threshold times 100, preserving off-step percent',async()=>{
 (api.fibPullbackScan as jest.Mock).mockResolvedValue([{symbol:'DIST',direction:'Bullish',fib_level_hit:'38.2',fib_dist_pct:1.54,at_level:true,confidence:61}]);render(<Page/>);fireEvent.click(screen.getByRole('button',{name:'Fib Pullback'}));fireEvent.change(screen.getAllByRole('spinbutton')[1],{target:{value:'1.55'}});
 await act(async()=>fireEvent.click(screen.getByRole('button',{name:'Run Scan'})));expect(screen.getByTitle(/Distance from current/)).toHaveAttribute('title',expect.stringContaining('≤1.55%'));fireEvent.click(screen.getByRole('button',{name:'Select DIST'}));expect(screen.getByRole('region',{name:'Evidence for DIST'})).toHaveTextContent('Applied tolerance 1.55%');
});
