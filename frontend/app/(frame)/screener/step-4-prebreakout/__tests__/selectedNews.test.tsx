import {act, fireEvent, render, screen, within} from '@testing-library/react';
import Page from '../page';
import {rememberScan, type ScanSnapshot} from '../scanThresholds';
import {api} from '@/lib/api';
import type {NewsItem} from '@/types/domain';
import {useScanStore} from '@/lib/scanStore';
import {useUniverseStore} from '@/lib/universeStore';
import {useRiskStore} from '@/lib/riskStore';

jest.mock('@/lib/api',()=>({api:{analyzeStock:jest.fn(()=>new Promise(()=>{})),getCandles:jest.fn(()=>Promise.resolve([])),getNews:jest.fn()}}));
jest.mock('@/components/organisms/SavedScanReportInspector',()=>({SavedScanReportInspector:()=>null}));
jest.mock('@/components/organisms/CompositeAlertDialog',()=>({CompositeAlertDialog:()=>null}));
jest.mock('../SelectedSetupChart',()=>({SelectedSetupChart:()=>null}));

const rows=()=>[{symbol:'AAA',direction:'Bearish',confidence:0,metrics:{}},{symbol:'BBB',direction:'Bullish',confidence:80,metrics:{}}];
const fibRows=()=>[{symbol:'FFF',direction:'Bearish',confidence:80,fib_level_hit:'38.2',fib_dist_pct:0,at_level:true,fib_swing:{low:100,high:200}}];
const snapshot:ScanSnapshot={scope:{mode:'prebreakout',direction:'Bearish',horizon:'Position (2–6 months)',symbols:['AAA','BBB'],universe:undefined,runId:'RUN'}};
const item=(over:Partial<NewsItem>={}):NewsItem=>({id:'n1',symbol:'AAA',headline:'AAA wins contract',source:'Reuters',timestamp:'2026-10-01T12:00:00Z',sentiment:'bull',url:'https://www.reuters.com/a',...over});
const news=()=>screen.getByRole('region',{name:'Selected stock news'});
function select(symbol='AAA'){fireEvent.click(screen.getByRole('button',{name:`Select ${symbol}`}));}

beforeEach(()=>{
 jest.clearAllMocks();
 useUniverseStore.setState({pick:'SP500'});
 const r=rows();rememberScan(r,snapshot);
 useScanStore.setState({context:null,preBreakoutResults:r,fibPullbackResults:fibRows() as never});
 useRiskStore.setState({limits:{...useRiskStore.getState().limits,portfolioValue:54321,maxLossPerTradePct:.007}});
 (api.getNews as jest.Mock).mockResolvedValue([item()]);
});

test('no selection: no fetch, explanatory empty state, scope/source and industry unavailability stated, placed below stock cards',()=>{
 render(<Page/>);
 expect(api.getNews).not.toHaveBeenCalled();
 const region=news();
 expect(within(region).getByText(/Select a candidate to load its headlines/)).toBeInTheDocument();
 expect(within(region).getByText(/Selected-symbol headlines from the app's news feed/)).toBeInTheDocument();
 expect(within(region).getByText(/Headlines · publisher · date · original link/)).toBeInTheDocument();
 expect(within(region).getByText(/Industry news unavailable — no supported industry mapping or industry news feed/)).toBeInTheDocument();
 const scores=screen.getByRole('region',{name:'Selected stock score context'});
 expect(scores.compareDocumentPosition(region)&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});

test('selected symbol only is fetched; headline, publisher, date and a safe external original link render; sentiment never shown',async()=>{
 render(<Page/>);await act(async()=>select());
 expect(api.getNews).toHaveBeenCalledTimes(1);expect(api.getNews).toHaveBeenCalledWith(['AAA']);
 const region=news();
 expect(within(region).getByText('AAA · Stock & industry news')).toBeInTheDocument();
 expect(within(region).getByText('AAA wins contract')).toBeInTheDocument();
 expect(within(region).getByText(/Reuters/)).toBeInTheDocument();
 expect(within(region).getByText(/2026-10-01 12:00 UTC/)).toBeInTheDocument();
 const link=within(region).getByRole('link',{name:/Original article/});
 expect(link).toHaveAttribute('href','https://www.reuters.com/a');
 expect(link).toHaveAttribute('target','_blank');
 expect(link).toHaveAttribute('rel','noopener noreferrer');
 expect(region).not.toHaveTextContent(/sentiment|\bbull\b|\bbear\b|neutral/i);
});

test.each([
 ['javascript scheme','javascript:alert(1)'],['relative path','/news/a'],['ftp scheme','ftp://x.example/a'],
 ['missing',undefined],['null',null],['empty',''],['no host','https://'],
])('%s link is explicitly unavailable, never a constructed anchor',async(_label,url)=>{
 (api.getNews as jest.Mock).mockResolvedValue([item({url:url as string|null|undefined})]);
 render(<Page/>);await act(async()=>select());
 const region=news();
 expect(within(region).getByText('AAA wins contract')).toBeInTheDocument();
 expect(within(region).queryByRole('link')).not.toBeInTheDocument();
 expect(within(region).getByText(/Original link unavailable/)).toBeInTheDocument();
});

test('blank publisher and blank/unparseable date use explicit fallbacks without invented values',async()=>{
 (api.getNews as jest.Mock).mockResolvedValue([item({id:'a',source:'',timestamp:''}),item({id:'b',headline:'Second',source:'  ',timestamp:'not a date'})]);
 render(<Page/>);await act(async()=>select());
 const region=news();
 expect(within(region).getAllByText(/Publisher unavailable/)).toHaveLength(2);
 expect(within(region).getAllByText(/Date unavailable/)).toHaveLength(2);
});

test('no news returned → local empty state',async()=>{
 (api.getNews as jest.Mock).mockResolvedValue([]);
 render(<Page/>);await act(async()=>select());
 expect(within(news()).getByText(/No headlines returned for AAA/)).toBeInTheDocument();
});

test('upstream error is local: table, chart shell and stock context stay',async()=>{
 (api.getNews as jest.Mock).mockRejectedValue(new Error('boom'));
 render(<Page/>);await act(async()=>select());
 expect(within(news()).getByText(/Headlines unavailable for AAA — news request failed/)).toBeInTheDocument();
 expect(screen.getByRole('button',{name:'Select AAA'})).toHaveAttribute('aria-pressed','true');
 expect(screen.getByRole('button',{name:'Select BBB'})).toBeInTheDocument();
 expect(screen.getByRole('region',{name:'Selected setup chart'})).toBeInTheDocument();
 expect(screen.getByRole('region',{name:'Selected stock score context'})).toBeInTheDocument();
});

test('loading state is local and late replies for a previous selection are ignored',async()=>{
 const pending:Array<{resolve:(v:NewsItem[])=>void;reject:(e:Error)=>void}>=[];
 (api.getNews as jest.Mock).mockImplementation(()=>new Promise((resolve,reject)=>pending.push({resolve,reject})));
 render(<Page/>);await act(async()=>select());
 expect(within(news()).getByText(/Loading headlines for AAA/)).toBeInTheDocument();
 await act(async()=>select('BBB'));
 expect(api.getNews).toHaveBeenLastCalledWith(['BBB']);
 await act(async()=>pending[0].resolve([item({headline:'Old AAA headline'})]));
 expect(screen.queryByText('Old AAA headline')).not.toBeInTheDocument();
 expect(within(news()).getByText(/Loading headlines for BBB/)).toBeInTheDocument();
 await act(async()=>pending[1].resolve([item({id:'b',symbol:'BBB',headline:'BBB headline'})]));
 expect(within(news()).getByText('BBB headline')).toBeInTheDocument();
 await act(async()=>pending[0].reject(new Error('late')));
 expect(within(news()).getByText('BBB headline')).toBeInTheDocument();
 expect(screen.queryByText(/news request failed/)).not.toBeInTheDocument();
});

test('an item tagged with another ticker is labelled with its own symbol, not relabelled or dropped',async()=>{
 (api.getNews as jest.Mock).mockResolvedValue([item(),item({id:'m',symbol:'MSFT',headline:'Cross-listed story'})]);
 render(<Page/>);await act(async()=>select());
 const region=news();
 const other=within(region).getByText('Cross-listed story').closest('li') as HTMLElement;
 expect(other).toHaveTextContent(/Tagged MSFT/);expect(other).toHaveTextContent(/returned for requested AAA/);
 const own=within(region).getByText('AAA wins contract').closest('li') as HTMLElement;
 expect(own).toHaveTextContent(/Tagged AAA/);expect(own).not.toHaveTextContent(/returned for requested/);
});

test('mode change clears stale headlines; Fib mode selection loads its own symbol news',async()=>{
 render(<Page/>);await act(async()=>select());
 expect(within(news()).getByText('AAA wins contract')).toBeInTheDocument();
 await act(async()=>fireEvent.click(screen.getByRole('button',{name:'Fib Pullback'})));
 expect(screen.queryByText('AAA wins contract')).not.toBeInTheDocument();
 expect(within(news()).getByText(/Select a candidate to load its headlines/)).toBeInTheDocument();
 (api.getNews as jest.Mock).mockResolvedValue([item({symbol:'FFF',headline:'FFF headline'})]);
 await act(async()=>select('FFF'));
 expect(api.getNews).toHaveBeenLastCalledWith(['FFF']);
 expect(within(news()).getByText('FFF headline')).toBeInTheDocument();
});
