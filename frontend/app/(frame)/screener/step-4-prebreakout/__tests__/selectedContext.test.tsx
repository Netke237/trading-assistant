import {act, fireEvent, render, screen, within} from '@testing-library/react';
import Page from '../page';
import {rememberScan, type ScanSnapshot} from '../scanThresholds';
import {api, type StockAnalysis} from '@/lib/api';
import {useScanStore} from '@/lib/scanStore';
import {useUniverseStore} from '@/lib/universeStore';
import {useRiskStore} from '@/lib/riskStore';
jest.mock('@/lib/api',()=>({api:{analyzeStock:jest.fn(),getCandles:jest.fn(()=>Promise.resolve([]))}}));
jest.mock('@/components/organisms/SavedScanReportInspector',()=>({SavedScanReportInspector:()=>null}));
jest.mock('../SelectedSetupChart',()=>({SelectedSetupChart:()=>null}));
const rows=()=>[{symbol:'AAA',direction:'Bearish',confidence:0,metrics:{}},{symbol:'BBB',direction:'Bullish',confidence:80,metrics:{}}];
const snapshot:ScanSnapshot={scope:{mode:'prebreakout',direction:'Bearish',horizon:'Position (2–6 months)',symbols:['AAA','BBB'],universe:undefined,runId:'RUN'}};
const analysis=(symbol='AAA',direction='Bearish'):StockAnalysis=>({symbol,direction,company:`Company ${symbol}`,price:12,stock_score:0,stock_status:'REJECT',is_index:false,strategy:null,backtest:null,confidence:null,confidence_text:null,sentiment:null,fundamentals:null,next_event_days:null,next_event_label:null,rules:[],gate_flags:[{gate:'score',status:'REJECT',detail:'Score below minimum'}],ema_trend:null,iv_rank:null,regime_by_horizon:{},sector:null,sector_rs:null,market_backdrop:{overall:'CAUTION',direction:'Bullish',vix:0}});
function select(symbol='AAA'){fireEvent.click(screen.getByRole('button',{name:`Select ${symbol}`}));}
beforeEach(()=>{jest.clearAllMocks();useUniverseStore.setState({pick:'SP500'});const r=rows();rememberScan(r,snapshot);useScanStore.setState({context:null,preBreakoutResults:r,fibPullbackResults:[]});useRiskStore.setState({limits:{...useRiskStore.getState().limits,portfolioValue:54321,maxLossPerTradePct:.007}});(api.analyzeStock as jest.Mock).mockResolvedValue(analysis());});
test('scoped live request uses selected direction/captured horizon and real risk; panels follow amended placement',async()=>{
 render(<Page/>);await act(async()=>select());
 expect(api.analyzeStock).toHaveBeenCalledWith(expect.objectContaining({symbol:'AAA',direction:'Bearish',horizon:'Position',strategy:'pullback_ema',account_size:54321,risk_pct:.007}));
 const top=screen.getByRole('region',{name:'Selected sentiment and fundamentals'}),score=screen.getByRole('region',{name:'Selected stock score context'});
 expect(screen.getByRole('button',{name:'Run Scan'}).compareDocumentPosition(top)&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
 expect(top.compareDocumentPosition(screen.getByRole('button',{name:'Select AAA'}))&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
 expect(screen.getByRole('region',{name:'Selected setup chart'}).compareDocumentPosition(score)&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
 expect(within(score).getByText(/Stock score: 0/)).toBeInTheDocument();expect(within(score).getByText(/Historical signal confidence: Unavailable/)).toBeInTheDocument();
 expect(screen.getAllByText(/Separately fetched/).length).toBeGreaterThan(0);expect(screen.getAllByText(/Historical matched setup evidence unavailable/).length).toBeGreaterThan(0);
 expect(within(top).getByText(/Market backdrop.*Bullish.*CAUTION/)).toBeInTheDocument();
 expect(screen.getAllByText(/Score below minimum/).length).toBeGreaterThan(0);
});
test('legacy scope never falls back to live controls or launches analysis',async()=>{useScanStore.setState({preBreakoutResults:rows()});render(<Page/>);await act(async()=>select());expect(api.analyzeStock).not.toHaveBeenCalled();expect(screen.getAllByText(/Captured horizon unavailable/).length).toBeGreaterThan(0);});
test('late response and stale fields are refused across symbol and result-array identity',async()=>{
 const pending:Array<(a:StockAnalysis)=>void>=[];(api.analyzeStock as jest.Mock).mockImplementation(()=>new Promise(resolve=>pending.push(resolve)));render(<Page/>);await act(async()=>select());await act(async()=>select('BBB'));
 await act(async()=>pending[0](analysis()));expect(screen.queryByText('Company AAA')).not.toBeInTheDocument();await act(async()=>pending[1](analysis('BBB','Bullish')));expect(screen.getAllByText(/Company BBB/).length).toBeGreaterThan(0);
 const replacement=rows();rememberScan(replacement,snapshot);act(()=>useScanStore.setState({preBreakoutResults:replacement}));expect(screen.queryByText(/Company BBB/)).not.toBeInTheDocument();
 await act(async()=>{});await act(async()=>pending[2](analysis('BBB','Bullish')));expect(screen.getAllByText(/Company BBB/).length).toBeGreaterThan(0);
});
test.each([analysis('OTHER'),analysis('AAA','Bullish')])('mismatched response identity exposes no fields',async(response)=>{(api.analyzeStock as jest.Mock).mockResolvedValue(response);render(<Page/>);await act(async()=>select());expect(screen.queryByText(/Stock score: 0/)).not.toBeInTheDocument();expect(screen.getAllByText(/Response identity mismatch/).length).toBeGreaterThan(0);});
test('live horizon control changes cannot relabel existing captured context',async()=>{render(<Page/>);await act(async()=>select());act(()=>useScanStore.setState({context:{direction:'Bullish',horizon:'Intraday'} as never}));expect(api.analyzeStock).toHaveBeenCalledTimes(1);expect(screen.getAllByText(/requested horizon Position/).length).toBeGreaterThan(0);});

import {compatibleExplanation, SelectedStockScores, SelectedSentimentFundamentals} from '../SelectedStockContext';
import type {StockExplanation} from '@/types/domain';
const evidence=():StockExplanation=>({version:1,symbol:'AAA',direction:'Bearish',horizon:'Position',scoring_mode:'stock',iv_basis:'none',evaluated_at:'2026-10-14T00:00:00Z',score:0,status:'CAUTION',raw_status:'REJECT',unrounded_score:0.123456,rounding:'python_round_ties_to_even',pass_threshold:65,caution_threshold:45,weights:{trend:.3,pullback:.2,trigger:.2,event:.2,vol:.1},components:Object.fromEntries(['trend','pullback','trigger','event','vol'].map(name=>[name,{name,wire_name:name,raw_score:0,status:'REJECT',measured:name!=='trigger',weight:0,contribution:0,detail:{note:'Actual observation',nullable:null},config:{threshold:0}}])),caps:[{name:'safety',status:'CAUTION',before:'PASS',after:'CAUTION',detail:{note:'Actual safety cap'},config:{threshold:0}}],gate_config:{confidence:{reject_below:0},unknown:null}} as StockExplanation);
test('complete live explanation preserves zero, qualification, notes, weights, caps and gate data',()=>{
 const data={...analysis(),stock_explanation:evidence()};render(<SelectedStockScores context={{row:rows()[0],mode:'prebreakout',snapshot,reason:'',live:{request:{symbol:'AAA',direction:'Bearish',horizon:'Position',strategy:'pullback_ema',account_size:54321,risk_pct:.007},data,fetchedAt:'2026-10-14T01:00:00Z'}}}/>);
 expect(screen.getByText(/raw total 0.123456/)).toHaveTextContent('raw status REJECT');
 expect(screen.getAllByText('Weight 0 · Contribution 0')).toHaveLength(5);expect(screen.getByText('Unmeasured')).toBeInTheDocument();
 expect(screen.getByText('Scorer caps and safety explanations').parentElement).toHaveTextContent('Actual safety cap');
 expect(screen.getByText('Applied gate configuration').parentElement).toHaveTextContent('reject_below');
 expect(screen.getByLabelText('trend component')).toHaveTextContent('nullable');
});
test.each([{symbol:'OTHER'},{direction:'Bullish'},{horizon:'Swing'},{score:10},{scoring_mode:'options'},{version:2}])('incompatible explanation is unavailable: %j',(change)=>{
 const bad={...evidence(),...change} as StockExplanation;expect(compatibleExplanation(bad,'AAA','Bearish','Position',0)).toBeNull();
 render(<SelectedStockScores context={{row:rows()[0],mode:'prebreakout',snapshot,reason:'',live:{request:{symbol:'AAA',direction:'Bearish',horizon:'Position',strategy:'pullback_ema'},data:{...analysis(),stock_explanation:bad},fetchedAt:'now'}}}/>);
 expect(screen.getByText(/Complete score evidence unavailable/)).toBeInTheDocument();expect(screen.queryByText(/raw total 0.123456/)).not.toBeInTheDocument();
});
test('original Pullback evidence wins over live data and fundamentals safety/zero remain accessible',()=>{
 const original={...analysis(),strategy:{strategy:'pullback_ema'},backtest:{passes_gate:false},confidence:0,confidence_text:'Unvalidated original',shares:1,dollar_risk:1,dollar_size:1,stock_explanation:evidence(),fundamentals:{score:0,quality_label:'Weak',risk_label:'High',growth_score:0,quality_score:0,risk_score:0,safety_flags:['negative_equity'],detail:{observed:0}},sentiment:{horizon:'Position',timeframe:'Daily',state:'Bear',p_stay:0,stability:'Low',regime_age_days:0,avg_regime_duration:0,conviction_pct:-30,conviction_label:'Strong Bearish',interpretation:'Bearish measured context',hmm_state:null,alignment:'Unavailable',insufficient_data:false}} as never;
 const c={row:original,mode:'pullback' as const,snapshot:{...snapshot,scope:{...snapshot.scope,mode:'pullback' as const}},reason:'',live:{request:{symbol:'AAA',direction:'Bearish' as const,horizon:'Position' as const,strategy:'pullback_ema' as const},data:{...analysis(),stock_score:99},fetchedAt:'now'}};
 render(<><SelectedSentimentFundamentals context={c}/><SelectedStockScores context={c}/></>);
 expect(screen.getByText('Stock score: 0 / 100')).toBeInTheDocument();expect(screen.queryByText(/Stock score: 99/)).not.toBeInTheDocument();expect(screen.getByText('Historical signal confidence: 0')).toBeInTheDocument();
 expect(screen.getAllByText(/negative equity/).length).toBeGreaterThan(0);expect(screen.getAllByText(/Strong Bearish/).length).toBeGreaterThan(0);expect(screen.getByText('Complete original Pullback disclosure').parentElement).toHaveTextContent('Unvalidated original');
});
test('zero supplied risk is refused instead of defaulting to positive analysis sizing',async()=>{useRiskStore.setState({limits:{...useRiskStore.getState().limits,maxLossPerTradePct:0}});render(<Page/>);await act(async()=>select());expect(api.analyzeStock).not.toHaveBeenCalled();expect(screen.getAllByText(/positive account size and risk/).length).toBeGreaterThan(0);});
test('missing original Pullback components stay unavailable alongside distinctly scoped live components and total',()=>{
 const original={...analysis(),stock_score:15,stock_explanation:null,strategy:{strategy:'pullback_ema'},backtest:{passes_gate:false},confidence:0,shares:1,dollar_risk:1,dollar_size:1} as never;
 const c={row:original,mode:'pullback' as const,snapshot:{...snapshot,scope:{...snapshot.scope,mode:'pullback' as const}},reason:'',live:{request:{symbol:'AAA',direction:'Bearish' as const,horizon:'Position' as const,strategy:'pullback_ema' as const},data:{...analysis(),stock_explanation:evidence()},fetchedAt:'2026-10-14T00:00:00Z'}};
 render(<SelectedStockScores context={c}/>);const primary=screen.getByRole('region',{name:'Selected stock score context'}),supplement=screen.getByRole('region',{name:'Supplementary live stock score context'});
 expect(primary).toHaveTextContent('Stock score: 15');expect(primary).toHaveTextContent('Historical signal confidence: 0');expect(primary).toHaveTextContent('Complete score evidence unavailable');
 expect(supplement).toHaveTextContent('Stock score: 0');expect(supplement).toHaveTextContent('raw total 0.123456');expect(supplement).toHaveTextContent('Separately fetched');expect(supplement).toHaveTextContent('Historical matched setup evidence unavailable');
});
test('late failure cannot erase a newer symbol success',async()=>{
 let rejectOld!:(e:Error)=>void;(api.analyzeStock as jest.Mock).mockImplementationOnce(()=>new Promise((_resolve,reject)=>{rejectOld=reject;})).mockResolvedValueOnce(analysis('BBB','Bullish'));
 render(<Page/>);await act(async()=>select());await act(async()=>select('BBB'));await act(async()=>rejectOld(new Error('Old failure')));
 expect(screen.getAllByText(/Company BBB/).length).toBeGreaterThan(0);expect(screen.queryByText(/analysis request failed/)).not.toBeInTheDocument();
});
test('live sentiment for another horizon is unavailable while same-symbol fundamentals remain supplied',async()=>{
 const data={...analysis(),sentiment:{horizon:'Swing',timeframe:'Daily',state:'Bear',p_stay:0,stability:'Low',regime_age_days:0,avg_regime_duration:0,conviction_pct:-30,conviction_label:'Strong Bearish',interpretation:'Wrong horizon',hmm_state:null,alignment:'Unavailable',insufficient_data:false},fundamentals:{score:0,quality_label:'Weak',risk_label:'High',growth_score:0,quality_score:0,risk_score:0,safety_flags:[],detail:{observed:0}}};(api.analyzeStock as jest.Mock).mockResolvedValue(data);
 render(<Page/>);await act(async()=>select());expect(screen.queryByText(/Wrong horizon/)).not.toBeInTheDocument();expect(screen.getByText(/Selected-stock sentiment unavailable/)).toBeInTheDocument();expect(screen.getByText('Complete fundamental evidence and safety flags').parentElement).toHaveTextContent('observed');
});
test.each([[25,'Supports selected direction'],[-25,'Opposes selected direction']] as const)('Bearish source conviction %s is already direction-aligned',(conviction_pct,label)=>{
 const data={...analysis(),sentiment:{horizon:'Position',timeframe:'Daily',state:'Bear',p_stay:0,stability:'Low',regime_age_days:0,avg_regime_duration:0,conviction_pct,conviction_label:'Source conviction',interpretation:'Direction-aligned source',hmm_state:null,alignment:'Unavailable',insufficient_data:false}};
 render(<SelectedSentimentFundamentals context={{row:rows()[0],mode:'prebreakout',snapshot,reason:'',live:{request:{symbol:'AAA',direction:'Bearish',horizon:'Position',strategy:'pullback_ema'},data,fetchedAt:'now'}}}/>);
 expect(screen.getByText(new RegExp(label))).toBeInTheDocument();expect(screen.getByText(new RegExp(`Source conviction.*${conviction_pct}%`))).toHaveTextContent(`${conviction_pct}% conviction`);
});
