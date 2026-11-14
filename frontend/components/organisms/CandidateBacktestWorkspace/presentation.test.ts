import type { DetailedBacktestResult, BacktestTrade } from '@/types/backtest';
import { performanceSeries, performanceSummary, sampledDrawdown, displayBounds, clampBounds, exactSample, tradePage, formatValue, formatSigned, formatPerformance, performanceComparison, legendReadout, drawdownReadout, exitReasonLabel, tradeWindow, pageOfTrade, formatUtcMinute } from './presentation';

const time = (iso: string) => Date.parse(iso) / 1000;
function freeze<T>(value: T): T {
 if (value && typeof value === 'object') { Object.values(value).forEach(freeze); Object.freeze(value); }
 return value;
}
const detail = freeze<DetailedBacktestResult>({
 status:'success',reason:null,initial_equity:1000,
 summary:{strategy:'test',direction:'Bearish',n_trades:0,win_rate:0,total_return_pct:7.123,max_drawdown_pct:8.25,expectancy:0,sharpe:0,confidence:null,passes_gate:false,summary_text:'engine',n_time_exits:0},
 candles:[{time:10,open:20,high:21,low:19,close:20,volume:2},{time:30,open:22,high:23,low:21,close:22,volume:2}],input_candles:[],
 equity:[{time:10,equity:900,strategy_index:90,benchmark_index:101},{time:20,equity:1200,strategy_index:120,benchmark_index:105},{time:40,equity:1080,strategy_index:108,benchmark_index:110.25}],
 trades:[],open_positions:[{id:'open',direction:'Bearish',entry_time:10,entry_price:20,size:-1,unrealized_pnl:80}],
 configuration:{initial_cash:1000,commission:0.001,commission_basis:'relative',order_size:0.9,sizing:'recorded',margin:1,spread:0,exclusive_orders:true,trade_on_close:false,finalize_trades:false,hold_max_days:null,entry_start:null,entry_end:null},
 effective_params:{},engine_contract_version:'test',time_basis:'UTC epoch seconds',
});

test('retains recorded 100 baseline and long benchmark, separate from engine summary and open P&L',()=>{
 expect(performanceSeries(detail,'percent')).toEqual({strategy:[{time:10,value:-10},{time:20,value:20},{time:40,value:8}],benchmark:[{time:10,value:1},{time:20,value:5},{time:40,value:10.25}]});
 expect(performanceSeries(detail,'index').strategy?.[0]).toEqual({time:10,value:90});
 expect(performanceSummary(detail)).toEqual({engineReturn:7.123,engineMaxDrawdown:8.25,closedTrades:0,winRate:0,strategyReturn:8,benchmarkReturn:10.25,difference:-2.25,time:40});
 expect(detail.equity[0].strategy_index).toBe(90);
 expect(detail.open_positions[0].unrealized_pnl).toBe(80);
});
test('keeps zero, negative and full precision before formatting',()=>{
 expect(performanceSummary({...detail,equity:[{time:1,equity:0,strategy_index:0,benchmark_index:-5}]})).toMatchObject({strategyReturn:-100,benchmarkReturn:-105,difference:5});
 expect(performanceSummary({...detail,equity:[{time:1,equity:1,strategy_index:100.004,benchmark_index:100.001}]}).difference).toBeCloseTo(0.003,12);
 expect(performanceSummary({...detail,equity:[{time:1,equity:1,strategy_index:100,benchmark_index:100}]}).difference).toBe(0);
 expect(formatValue(0)).toBe('0.00');expect(formatValue(-2.25)).toBe('-2.25');
 expect(formatValue(null)).toBe('Unavailable');expect(formatValue(Infinity)).toBe('Unavailable');
});
test('invalid or missing series are unavailable while engine summary remains inspectable',()=>{
 expect(performanceSeries({...detail,equity:[]},'percent')).toEqual({strategy:null,benchmark:null});
 expect(performanceSummary({...detail,equity:[]})).toMatchObject({engineReturn:7.123,strategyReturn:null,benchmarkReturn:null,difference:null,time:null});
 const bad={...detail,equity:[{...detail.equity[0],strategy_index:NaN},detail.equity[2]]};
 expect(performanceSeries(bad,'percent').strategy).toBeNull();expect(performanceSeries(bad,'percent').benchmark).toHaveLength(2);
 expect(performanceSummary(bad)).toMatchObject({strategyReturn:null,benchmarkReturn:10.25,difference:null});
 expect(performanceSeries({...detail,equity:[{...detail.equity[0],time:NaN}]},'index')).toEqual({strategy:null,benchmark:null});
});
test('drawdown seeds the initial peak over full history before slicing',()=>{
 const samples=sampledDrawdown(detail);
 expect(samples?.[0].value).toBeCloseTo(-10,12);expect(samples?.[1]).toEqual({time:20,value:0});
 expect(samples?.filter(row=>row.time>=40)[0].value).toBeCloseTo(-10,12);
 expect(detail.summary.max_drawdown_pct).toBe(8.25);
});
test('legitimate zero/negative equity losses survive but any invalid drawdown sample invalidates the series',()=>{
 expect(sampledDrawdown({...detail,equity:[{...detail.equity[0],equity:0},{...detail.equity[1],equity:-250}]})).toEqual([{time:10,value:-100},{time:20,value:-125}]);
 for(const initial_equity of [0,-1,NaN,Infinity]) expect(sampledDrawdown({...detail,initial_equity})).toBeNull();
 for(const equity of [NaN,Infinity,-Infinity]) expect(sampledDrawdown({...detail,equity:[detail.equity[0],{...detail.equity[1],equity},detail.equity[2]]})).toBeNull();
 expect(sampledDrawdown({...detail,equity:[]})).toBeNull();
});
test('timestamp lookup never substitutes candle/equity indices or nearest sessions',()=>{
 expect(exactSample(detail.candles,20)).toBeNull();expect(exactSample(detail.equity,20)?.strategy_index).toBe(120);
 expect(exactSample(detail.candles,30)?.close).toBe(22);expect(exactSample(detail.equity,30)).toBeNull();
 expect(exactSample(detail.equity,null)).toBeNull();expect(displayBounds(detail,'all')).toEqual({from:10,to:40});
 expect(clampBounds({from:0,to:25},{from:10,to:40})).toEqual({from:10,to:25});
 expect(clampBounds({from:50,to:60},{from:10,to:40})).toEqual({from:40,to:40});
 expect(clampBounds({from:30,to:20},{from:10,to:40})).toBeNull();
});
test('year bounds use UTC calendar year, clamp leap day and preserve intraday seconds',()=>{
 const leap=time('2024-02-29T15:45:30Z');
 const changed={...detail,candles:[],equity:[{...detail.equity[0],time:time('2022-01-01T00:00:00Z')},{...detail.equity[1],time:leap}]};
 expect(displayBounds(changed,'year')).toEqual({from:time('2023-02-28T15:45:30Z'),to:leap});
 expect(displayBounds({...changed,equity:[{...changed.equity[0],time:time('2023-12-01T09:15:00Z')},changed.equity[1]]},'year')?.from).toBe(time('2023-12-01T09:15:00Z'));
 expect(displayBounds({...detail,candles:[],equity:[]},'year')).toBeNull();
 expect(displayBounds({...detail,candles:[],equity:[detail.equity[0]]},'year')).toEqual({from:10,to:10});
});
const trade=(id:string,net_return_pct:number):BacktestTrade=>({id,net_return_pct,entry_time:10,exit_time:20,entry_price:43.125,exit_price:39.875,direction:'Bearish',size:-2,commission:1.25,exit_reason:'unknown'});
test('sorting/pagination retain exact immutable trades and stable ids through ties and partial pages',()=>{
 const trades=freeze([trade('b',7.123),trade('a',7.123),trade('c',-1),trade('d',0)]);
 const page=tradePage(trades,'net_return_pct','desc',0,2);
 expect(page.rows.map(row=>row.id)).toEqual(['a','b']);expect(page.rows[0]).toBe(trades[1]);expect(page.rows[0].entry_price).toBe(43.125);
 expect(page).toMatchObject({page:0,pageCount:2,total:4});
 expect(tradePage(trades,'net_return_pct','desc',1,3).rows.map(row=>row.id)).toEqual(['c']);
 expect(tradePage(trades,'entry_time','asc',99,2).page).toBe(1);
 expect(tradePage([],'entry_time','asc',0,10)).toEqual({rows:[],page:0,pageCount:0,total:0});
 expect(trades.map(row=>row.id)).toEqual(['b','a','c','d']);
});

test('signed display keeps sign, zero and unavailable without changing stored values',()=>{
 expect(formatSigned(8)).toBe('+8.00');expect(formatSigned(-2.25)).toBe('-2.25');expect(formatSigned(0)).toBe('0.00');
 expect(formatSigned(NaN)).toBe('Unavailable');expect(formatSigned(null)).toBe('Unavailable');
 expect(formatPerformance(20,'percent')).toBe('+20.00%');expect(formatPerformance(-10,'percent')).toBe('-10.00%');
 expect(formatPerformance(120,'index')).toBe('120.00');expect(formatPerformance(null,'index')).toBe('Unavailable');
 expect(formatPerformance(undefined,'percent')).toBe('Unavailable');
});
test('comparison compares unrounded final indices and keeps the engine return separately disclosed',()=>{
 const holding=performanceComparison(detail);
 expect(holding).toMatchObject({outcome:'holding_ahead',engineReturn:7.123,indexedReturn:8,engineDiffers:true});
 expect(holding.headline).toBe('Long buy-and-hold finished ahead of recorded strategy equity.');
 expect(holding.sentence).toBe('Recorded strategy equity returned +8.00%; long buy-and-hold returned +10.25%; difference -2.25 percentage points over the full recorded period.');
 const ahead=performanceComparison({...detail,equity:[{time:1,equity:1,strategy_index:100.004,benchmark_index:100.001}]});
 expect(ahead.outcome).toBe('strategy_ahead');expect(ahead.headline).toBe('Recorded strategy equity finished ahead of long buy-and-hold.');
 expect(ahead.sentence).toContain('difference +0.00 percentage points');
 const level=performanceComparison({...detail,summary:{...detail.summary,total_return_pct:0},equity:[{time:1,equity:1,strategy_index:100,benchmark_index:100}]});
 expect(level).toMatchObject({outcome:'equal',engineDiffers:false});expect(level.headline).toBe('Recorded strategy equity and long buy-and-hold finished level.');
 const missing=performanceComparison({...detail,equity:[]});
 expect(missing).toMatchObject({outcome:'missing',indexedReturn:null,engineReturn:7.123,engineDiffers:false});
 expect(missing.headline).toBe('Comparison unavailable.');
 expect(missing.sentence).toBe('Recorded strategy equity return: Unavailable; long buy-and-hold return: Unavailable. Both final recorded indices are required to compare them.');
 const half=performanceComparison({...detail,equity:[{...detail.equity[0],benchmark_index:NaN}]});
 expect(half.outcome).toBe('missing');expect(half.sentence).toContain('Recorded strategy equity return: -10.00%; long buy-and-hold return: Unavailable.');
});
test('legend defaults to final recorded values and hover reads exact samples only',()=>{
 expect(legendReadout(detail,'percent',null)).toEqual({time:40,hovered:false,strategy:8,benchmark:10.25});
 expect(legendReadout(detail,'index',null)).toEqual({time:40,hovered:false,strategy:108,benchmark:110.25});
 expect(legendReadout(detail,'percent',20)).toEqual({time:20,hovered:true,strategy:20,benchmark:5});
 expect(legendReadout(detail,'percent',30)).toEqual({time:30,hovered:true,strategy:null,benchmark:null});
 expect(legendReadout({...detail,equity:[]},'percent',null)).toEqual({time:null,hovered:false,strategy:null,benchmark:null});
});
test('drawdown readout reports latest and deepest sampled values, unavailable when the series is',()=>{
 const readout=drawdownReadout(sampledDrawdown(detail));
 expect(readout.latest).toBeCloseTo(-10,12);expect(readout.deepest).toBeCloseTo(-10,12);
 expect(drawdownReadout(sampledDrawdown({...detail,equity:[{...detail.equity[0],equity:850},detail.equity[1],detail.equity[2]]})).deepest).toBeCloseTo(-15,12);
 expect(drawdownReadout(null)).toEqual({latest:null,deepest:null});
});

describe('trade review helpers', () => {
 const DAY=86400, D=(n:number)=>1704067200+n*DAY;
 const daily=freeze<DetailedBacktestResult>({...detail,
  candles:Array.from({length:60},(_,n)=>({time:D(n),open:1,high:1,low:1,close:1,volume:1})),
  equity:Array.from({length:60},(_,n)=>({time:D(n),equity:1000,strategy_index:100,benchmark_index:100}))});
 const trade=(id:string,entry:number,exit:number,net=0):BacktestTrade=>({id,direction:'Bullish',entry_time:entry,exit_time:exit,entry_price:1,exit_price:1,size:1,net_return_pct:net,commission:0,exit_reason:'unknown'});
 test('labels only the two recorded exit reasons, never an invented stop or target',()=>{
  expect(exitReasonLabel('time')).toBe('Time exit (holding limit)');
  expect(exitReasonLabel('unknown')).toBe('Unknown (not recorded by engine)');
  expect(exitReasonLabel('stop' as never)).toBe('Unknown (not recorded by engine)');
 });
 test('zooms to the trade plus twenty recorded candle steps each side, clamped to recorded bounds',()=>{
  expect(tradeWindow(daily,trade('a',D(30),D(32)))).toEqual({from:D(10),to:D(52)});
  expect(tradeWindow(daily,trade('b',D(50),D(51)))).toEqual({from:D(30),to:D(59)});
  expect(tradeWindow(daily,trade('c',D(2),D(3)))).toEqual({from:D(0),to:D(23)});
  // A long trade pads by its own span instead.
  expect(tradeWindow(daily,trade('d',D(20),D(45)))).toEqual({from:D(0),to:D(59)});
  // Intraday steps are measured, not assumed daily.
  const intraday={...daily,candles:daily.candles.map((c,n)=>({...c,time:D(0)+n*900})),equity:daily.equity.map((e,n)=>({...e,time:D(0)+n*900}))};
  expect(tradeWindow(intraday,trade('e',D(0)+30*900,D(0)+31*900))).toEqual({from:D(0)+10*900,to:D(0)+51*900});
  // One recorded sample: no step, the window is the clamped trade itself.
  const single={...daily,candles:[daily.candles[5]],equity:[daily.equity[5]]};
  expect(tradeWindow(single,trade('f',D(5),D(5)))).toEqual({from:D(5),to:D(5)});
  expect(tradeWindow(daily,trade('g',NaN,D(5)))).toBeNull();
  expect(tradeWindow({...daily,candles:[],equity:[]},trade('h',D(5),D(6)))).toBeNull();
 });
 test('finds the page of a trade by stable id after sorting; unknown ids and empty lists have none',()=>{
  const trades=freeze([trade('t1',D(1),D(2),5),trade('t2',D(3),D(4),-1),trade('t3',D(5),D(6),9),trade('t4',D(7),D(8),2)]);
  expect(pageOfTrade(trades,'entry_time','asc',2,'t3')).toBe(1);
  expect(pageOfTrade(trades,'net_return_pct','desc',2,'t3')).toBe(0);
  expect(pageOfTrade(trades,'net_return_pct','desc',2,'t2')).toBe(1);
  expect(tradePage(trades,'net_return_pct','desc',pageOfTrade(trades,'net_return_pct','desc',2,'t2') as number,2).rows.map(r=>r.id)).toContain('t2');
  expect(pageOfTrade(trades,'entry_time','asc',2,'missing')).toBeNull();
  expect(pageOfTrade([],'entry_time','asc',2,'t1')).toBeNull();
 });
 test('formats row timestamps to the UTC minute without altering the recorded value',()=>{
  expect(formatUtcMinute(Date.parse('2024-06-03T14:30:59Z')/1000)).toBe('2024-06-03 14:30');
  expect(formatUtcMinute(NaN)).toBe('Unavailable');
 });
});
