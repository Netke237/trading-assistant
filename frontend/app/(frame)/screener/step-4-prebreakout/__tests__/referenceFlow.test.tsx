import {act, fireEvent, render, screen, within} from '@testing-library/react';
import Page from '../page';
import {api} from '@/lib/api';
import {useScanStore} from '@/lib/scanStore';
import {useUniverseStore} from '@/lib/universeStore';
import {useRiskStore} from '@/lib/riskStore';
jest.mock('@/lib/api',()=>({api:{prebreakoutScan:jest.fn(),fibPullbackScan:jest.fn(),postStockScan:jest.fn(),analyzeStock:jest.fn(),getNews:jest.fn()}}));
jest.mock('../SelectedSetupChart',()=>({SelectedSetupChart:()=> <div>Selected chart preserved</div>}));
jest.mock('@/components/organisms/SavedScanReportInspector',()=>({SavedScanReportInspector:({category,tableRunId}:{category:string;tableRunId:string})=><div>Saved report {category} {tableRunId}</div>}));
jest.mock('@/components/organisms/CompositeAlertDialog',()=>({CompositeAlertDialog:({symbol}:{symbol:string})=><div role="dialog">Alert {symbol}</div>}));
const modes=[['Pre-Breakout','Setup confidence','prebreakout'],['Pullback to EMA 50','Historical signal confidence','pullback'],['Fib Pullback','Fib proximity confidence','fib']] as const;
const stock=(symbol:string)=>({symbol,company:`${symbol} Company`,direction:'Bullish',price:0,stock_score:0,stock_status:'REJECT',confidence:0,strategy:{strategy:'pullback_ema'}});
beforeEach(()=>{
 jest.clearAllMocks();useUniverseStore.setState({pick:'SP500'});useScanStore.setState({context:{direction:'Bullish',horizon:'Swing'} as never,preBreakoutResults:[],fibPullbackResults:[]});
 useRiskStore.setState({limits:{...useRiskStore.getState().limits,portfolioValue:100000,maxLossPerTradePct:1}});
 (api.prebreakoutScan as jest.Mock).mockImplementation((_s,_d,_p,_u,metadata)=>{metadata({run_id:'PRE'});return Promise.resolve(['AAA','BBB'].map(symbol=>({symbol,direction:'Bullish',confidence:0,metrics:{atr_ratio:0,vol_ratio:null,proximity_pct:0}})));});
 (api.fibPullbackScan as jest.Mock).mockImplementation((_s,_d,_p,_u,metadata)=>{metadata({run_id:'FIB'});return Promise.resolve(['AAA','BBB'].map(symbol=>({symbol,direction:'Bullish',confidence:0,fib_level_hit:'38.2%',fib_dist_pct:0,at_level:false})));});
 (api.postStockScan as jest.Mock).mockResolvedValue({report_run_id:'EMA',candidates:['AAA','BBB'].map(stock)});
 (api.analyzeStock as jest.Mock).mockImplementation(({symbol})=>Promise.resolve(stock(symbol)));
 (api.getNews as jest.Mock).mockResolvedValue([]);
});
function disclosure(text:string){return screen.getByText(text).closest('details')!;}
test.each(modes)('%s follows controls → context → candidates/chart → closed qualification → parameters/news',async(button,header,mode)=>{
 render(<Page/>);fireEvent.click(screen.getByRole('button',{name:button}));
 const run=screen.getByRole('button',{name:'Run Scan'}),context=screen.getByRole('region',{name:'Selected sentiment and fundamentals'});
 for(const control of [run,screen.getByRole('textbox')])expect(control.compareDocumentPosition(context)&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
 expect(screen.getByText(header)).toBeInTheDocument();
 const qualification=disclosure('Stock Qualification'),parameters=disclosure('Scan parameters'),news=disclosure('Stock & industry news');
 for(const panel of [qualification,parameters,news])expect(panel).not.toHaveAttribute('open');
 expect(screen.getByRole('region',{name:'Selected setup chart'}).compareDocumentPosition(qualification)&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
 expect(qualification.compareDocumentPosition(parameters)&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
 await act(async()=>fireEvent.click(run));fireEvent.keyDown(screen.getByRole('button',{name:'Select BBB'}),{key:'Enter'});await act(async()=>{});
 const selected=screen.getByRole('button',{name:'Select BBB'});expect(selected).toHaveAttribute('aria-pressed','true');
 if(mode==='pullback')expect(qualification.querySelector('summary')).toHaveTextContent('Original Pullback');
 else {expect(qualification.querySelector('summary')).toHaveTextContent('supplementary pullback_ema');expect(qualification.querySelector('summary')).toHaveTextContent('does not qualify');}
 const counters=()=>[api.prebreakoutScan,api.fibPullbackScan,api.postStockScan,api.analyzeStock,api.getNews].map(fn=>(fn as jest.Mock).mock.calls.length),calls=counters();
 const scoreRegion=screen.getByRole('region',{name:'Selected stock score context',hidden:true});
 for(const panel of [qualification,parameters,news]){fireEvent.click(panel.querySelector('summary')!);fireEvent.click(panel.querySelector('summary')!);}
 expect(screen.getByRole('region',{name:'Selected stock score context',hidden:true})).toBe(scoreRegion);expect(counters()).toEqual(calls);
 expect(selected).toHaveAttribute('aria-pressed','true');expect(within(selected).getByText('0%')).toBeInTheDocument();
 fireEvent.click(screen.getByRole('button',{name:'Filter breakdown'}));expect(screen.getByText(`Saved report ${mode} ${mode==='prebreakout'?'PRE':mode==='fib'?'FIB':'EMA'}`)).toBeVisible();
 expect(within(selected).getByRole('button',{name:'Open BBB chart in a new tab'})).toBeInTheDocument();
 fireEvent.click(within(selected).getByRole('button',{name:'Alert'}));expect(screen.getByRole('dialog')).toHaveTextContent('BBB');
});
