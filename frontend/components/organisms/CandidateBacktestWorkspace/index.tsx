'use client';
import {useEffect,useId,useMemo,useRef,useState} from 'react';
import {createChart,CandlestickSeries,LineSeries,createSeriesMarkers,type IChartApi,type UTCTimestamp,type MouseEventParams,type SeriesMarker,type PriceFormat} from 'lightweight-charts';
import {useThemeStore} from '@/lib/theme';
import {Text,Data} from '@/components/primitives';
import type {BacktestArtifact} from '@/types/backtest';
import {historicalSeries,fillEvents,utc} from './chart';
import {performanceSeries,performanceSummary,performanceComparison,sampledDrawdown,legendReadout,drawdownReadout,displayBounds,exactSample,formatValue,formatSigned,formatPerformance,type PerformanceUnit} from './presentation';
import {linkPanes,type LinkedPane} from './paneSync';
import styles from './CandidateBacktestWorkspace.module.css';

type DisplayRange='all'|'year';
interface Visibility {strategy:boolean;benchmark:boolean}
/** Imperative display hooks into the live chart instances; none of them recreates a chart or touches evidence. */
interface PerformanceView {unit(unit:PerformanceUnit):void;visibility(show:Visibility):void;range(range:DisplayRange):void;height(expanded:boolean):void;restyle():void}

const PERFORMANCE_HEIGHT=320,EXPANDED_HEIGHT=520,DRAWDOWN_HEIGHT=130;
const percentFormat:PriceFormat={type:'custom',minMove:0.01,formatter:(value:number)=>`${value.toFixed(2)}%`};
const indexFormat:PriceFormat={type:'price',precision:2,minMove:0.01};
const timed=<T extends {time:number}>(rows:readonly T[])=>rows.map(r=>({...r,time:r.time as UTCTimestamp}));
const percentText=(value:number|null|undefined)=>{const text=formatValue(value);return text==='Unavailable'?text:`${text}%`;};

/** Frozen evidence owns its series and never subscribes to quotes or live strategy overlays. */
function Evidence({artifact}:{artifact:BacktestArtifact}) {
 const {detail,identity}=artifact;
 const runLabel=artifact.provenance==='fresh'?'Fresh backtest (separate result)':'Original backtest';
 const priceRef=useRef<HTMLDivElement>(null);
 const performanceRef=useRef<HTMLDivElement>(null);
 const drawdownRef=useRef<HTMLDivElement>(null);
 const [selected,setSelected]=useState<string|null>(null);
 const [unit,setUnit]=useState<PerformanceUnit>('percent');
 const [range,setRange]=useState<DisplayRange>('all');
 const [show,setShow]=useState<Visibility>({strategy:true,benchmark:true});
 const [expanded,setExpanded]=useState(false);
 const [hover,setHover]=useState<number|null>(null);
 const theme=useThemeStore(s=>s.theme);
 const titleId=useId();
 const curves=useMemo(()=>({percent:performanceSeries(detail,'percent'),index:performanceSeries(detail,'index')}),[detail]);
 const drawdown=useMemo(()=>sampledDrawdown(detail),[detail]);
 const view=useRef<PerformanceView|null>(null);
 // Latest display choices, read when the charts are (re)built so a rebuild keeps the view.
 const display=useRef({unit,range,show,expanded});
 display.current={unit,range,show,expanded};
 useEffect(()=>{
  if(!priceRef.current||!performanceRef.current)return;
  const chartOptions={timeScale:{timeVisible:true,secondsVisible:true},rightPriceScale:{minimumWidth:80}};
  const price=createChart(priceRef.current,{...chartOptions,height:360});
  const performance=createChart(performanceRef.current,{...chartOptions,height:display.current.expanded?EXPANDED_HEIGHT:PERFORMANCE_HEIGHT});
  const drawdownChart=drawdown&&drawdownRef.current?createChart(drawdownRef.current,{...chartOptions,height:DRAWDOWN_HEIGHT}):null;
  const charts:IChartApi[]=[price,performance,...(drawdownChart?[drawdownChart]:[])];
  const candle=price.addSeries(CandlestickSeries);
  // One shared right scale: both curves are in the same units, never dual-scaled.
  const strategy=performance.addSeries(LineSeries,{title:'Strategy equity',priceScaleId:'right',priceFormat:percentFormat});
  const benchmark=performance.addSeries(LineSeries,{title:'Long buy-and-hold (gross; excludes fees)',priceScaleId:'right',lineStyle:2,priceFormat:percentFormat});
  const drawdownSeries=drawdownChart?drawdownChart.addSeries(LineSeries,{title:'Sampled drawdown',priceFormat:percentFormat}):null;
  const data=historicalSeries(detail);
  candle.setData(timed(data.candles));
  if(drawdownSeries&&drawdown)drawdownSeries.setData(timed(drawdown));
  const fills=fillEvents(detail);
  const token=(name:string)=>getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const markers=createSeriesMarkers(candle,[]);
  const restyle=()=>{
   const bg=token('--bg-surface'),text=token('--text-secondary'),grid=token('--border-subtle'),accent=token('--accent'),pass=token('--pass'),reject=token('--reject');
   for(const chart of charts)chart.applyOptions({layout:{background:{color:bg},textColor:text},grid:{vertLines:{color:grid},horzLines:{color:grid}}});
   candle.applyOptions({upColor:pass,downColor:reject,borderUpColor:pass,borderDownColor:reject,wickUpColor:pass,wickDownColor:reject});
   strategy.applyOptions({color:accent});benchmark.applyOptions({color:text});drawdownSeries?.applyOptions({color:reject});
   const points:SeriesMarker<UTCTimestamp>[]=fills.filter(f=>f.candleTime!==null).map(f=>({id:f.id,time:f.candleTime as UTCTimestamp,position:'atPriceMiddle',price:f.price,shape:f.kind==='entry'?'arrowUp':'arrowDown',color:f.kind==='entry'?accent:text,text:`${f.direction} ${f.kind} @ ${f.price}`}));
   markers.setMarkers(points);
  };
  const hasPerformance=()=>curves.percent.strategy!==null||curves.percent.benchmark!==null;
  const panes:{pane:LinkedPane;hasData:()=>boolean}[]=[];
  const link=(chart:IChartApi,element:HTMLElement,hasData:()=>boolean,sampleAt:LinkedPane['sampleAt'])=>{const pane={chart,element,hasData,sampleAt};panes.push({pane,hasData});};
  link(price,priceRef.current,()=>data.candles.length>0,time=>{const row=exactSample(data.candles,time);return row?{value:row.close,series:candle}:null;});
  link(performance,performanceRef.current,hasPerformance,time=>{
   const {unit:current,show:visible}=display.current;
   for(const [key,series,on] of [['strategy',strategy,visible.strategy],['benchmark',benchmark,visible.benchmark]] as const){
    const rows=curves[current][key];const row=on&&rows?exactSample(rows,time):null;
    if(row)return {value:row.value,series};
   }
   return null;
  });
  if(drawdownChart&&drawdownSeries&&drawdownRef.current&&drawdown)link(drawdownChart,drawdownRef.current,()=>true,time=>{const row=exactSample(drawdown,time);return row?{value:row.value,series:drawdownSeries}:null;});
  const unlink=linkPanes(panes.map(p=>p.pane),setHover);
  const applyRange=(next:DisplayRange)=>{
   const bounds=displayBounds(detail,next);
   if(!bounds)return;
   for(const {pane,hasData} of panes)if(hasData())pane.chart.timeScale().setVisibleRange({from:bounds.from as UTCTimestamp,to:bounds.to as UTCTimestamp});
  };
  view.current={
   unit:next=>{
    // Same recorded timestamps either way, so the visible bars are kept exactly; values are never rebased.
    const keep=performance.timeScale().getVisibleLogicalRange();
    strategy.setData(timed(curves[next].strategy??[]));benchmark.setData(timed(curves[next].benchmark??[]));
    const priceFormat=next==='percent'?percentFormat:indexFormat;
    strategy.applyOptions({priceFormat});benchmark.applyOptions({priceFormat});
    if(keep)performance.timeScale().setVisibleLogicalRange(keep);
   },
   visibility:next=>{strategy.applyOptions({visible:next.strategy});benchmark.applyOptions({visible:next.benchmark});},
   range:applyRange,
   height:next=>performance.applyOptions({height:next?EXPANDED_HEIGHT:PERFORMANCE_HEIGHT}),
   restyle,
  };
  restyle();
  view.current.unit(display.current.unit);
  view.current.visibility(display.current.show);
  applyRange(display.current.range);
  const click=(p:MouseEventParams)=>{const fill=fills.find(f=>f.id===p.hoveredObjectId)||fills.find(f=>f.time===p.time);if(fill)setSelected(fill.tradeId);};
  price.subscribeClick(click);
  const containers=[priceRef.current,performanceRef.current,drawdownRef.current];
  const observer=new ResizeObserver(()=>{
   if(priceRef.current)price.applyOptions({width:priceRef.current.clientWidth});
   if(performanceRef.current)performance.applyOptions({width:performanceRef.current.clientWidth});
   if(drawdownChart&&drawdownRef.current)drawdownChart.applyOptions({width:drawdownRef.current.clientWidth});
  });
  for(const element of containers)if(element)observer.observe(element);
  return()=>{view.current=null;unlink();observer.disconnect();price.unsubscribeClick(click);markers.detach();for(const chart of charts)chart.remove();setHover(null);};
 },[detail,curves,drawdown]);
 // Display controls only adjust the existing charts: no rebuild, no run, no evidence change.
 useEffect(()=>{view.current?.unit(unit);},[unit]);
 useEffect(()=>{view.current?.visibility(show);},[show]);
 useEffect(()=>{view.current?.range(range);},[range]);
 useEffect(()=>{view.current?.height(expanded);},[expanded]);
 useEffect(()=>{view.current?.restyle();},[theme]);
 const trade=detail.trades.find(t=>t.id===selected);
 const summary=performanceSummary(detail);
 const comparison=performanceComparison(detail);
 const legend=legendReadout(detail,unit,hover);
 const drawdownNow=drawdownReadout(drawdown);
 const yearBounds=displayBounds(detail,'year');
 const performanceAvailable=curves.percent.strategy!==null||curves.percent.benchmark!==null;
 const legendTime=legend.time===null?'Unavailable':utc(legend.time);
 const readout=!legend.hovered?`Period end · ${legendTime}`:legend.strategy===null&&legend.benchmark===null?`${legendTime} · no recorded equity sample`:legendTime;
 const engineText=formatPerformance(comparison.engineReturn,'percent'),indexedText=formatPerformance(comparison.indexedReturn,'percent');
 // Unrounded values are compared; a difference hidden by display rounding is still disclosed, never called equal.
 const engineDisclosure=`Engine total return (summary definition): ${engineText}. Indexed ending change of recorded strategy equity: ${indexedText}.`
  +(!comparison.engineDiffers?'':engineText===indexedText?' These differ only beyond the two displayed decimals.':' These differ: the comparison above uses the recorded equity indices, and the engine figure keeps its own definition.')
  +' Summary metrics retain engine rounding and definitions.';
 const differenceTone=summary.difference===null||summary.difference===0?'primary':summary.difference>0?'pass':'reject';
 const pressed=(on:boolean)=>on?`${styles.toggle} ${styles.toggleOn}`:styles.toggle;
 const card=(label:string,value:string,note:string,tone:'primary'|'accent'|'pass'|'reject'='primary')=><div className={styles.metric}>
  <Text as="div" size={11} tone="secondary">{label}</Text><Data as="div" size={24} tone={tone} className={styles.metricValue}>{value}</Data><Text as="span" size={11} tone="dim" className={styles.metricNote}>{note}</Text>
 </div>;
 return <section className={styles.workspace} aria-label={artifact.provenance==='fresh'?'Fresh backtest evidence':'Original backtest evidence'}>
  <h1>{identity.symbol} — {runLabel}</h1>
  <p>{identity.strategy} · {identity.direction} · {identity.horizon} · {artifact.provenance==='fresh'?'Fresh':'Original'} interval: {identity.interval}</p>
  <p>Frozen historical evidence. Live overlays are separate. Time basis: {detail.time_basis}.</p>
  <section className={styles.metrics} aria-label="Full-period performance summary">
   {card('Strategy return (engine)',formatPerformance(summary.engineReturn,'percent'),'Engine summary total return','accent')}
   {card('Buy & hold return',formatPerformance(summary.benchmarkReturn,'percent'),'Long benchmark · gross, excludes fees')}
   {card('Strategy minus holding',formatSigned(summary.difference),'Percentage points of equity-index return · full period',differenceTone)}
   {card('Engine max drawdown',percentText(summary.engineMaxDrawdown),'Recorded engine metric · not the sampled pane',summary.engineMaxDrawdown<0?'reject':'primary')}
   {card('Winning closed trades',percentText(Number.isFinite(summary.winRate)?summary.winRate*100:null),'Engine win rate of closed trades')}
   {card('Closed trades',Number.isFinite(summary.closedTrades)?String(summary.closedTrades):'Unavailable','Engine count · open positions excluded')}
  </section>
  <section className={expanded?`${styles.panel} ${styles.expanded}`:styles.panel} aria-labelledby={titleId}>
   <div className={styles.panelHead}>
    <div>
     <Text as="div" size={10} tone="dim" className={styles.eyebrow}>01 / PERFORMANCE</Text>
     <h2 id={titleId} className={styles.panelTitle}>Strategy versus buying &amp; holding</h2>
     <Text as="p" size={12} tone="secondary" className={styles.subtitle}>Same recorded starting value of 100. Same recorded timestamps. Higher means a larger cumulative return.</Text>
    </div>
    <div className={styles.controls} role="group" aria-label="Performance display">
     <Text size={11} tone="secondary">Display</Text>
     <button type="button" className={pressed(unit==='percent')} aria-pressed={unit==='percent'} onClick={()=>setUnit('percent')}>Return %</button>
     <button type="button" className={pressed(unit==='index')} aria-pressed={unit==='index'} onClick={()=>setUnit('index')}>Index 100</button>
     <span className={styles.separator} aria-hidden="true"/>
     <button type="button" className={pressed(range==='year')} aria-pressed={range==='year'} onClick={()=>setRange('year')}>Last year</button>
     <button type="button" className={pressed(range==='all')} aria-pressed={range==='all'} onClick={()=>setRange('all')}>All history</button>
     <button type="button" className={pressed(expanded)} aria-pressed={expanded} onClick={()=>setExpanded(v=>!v)}>{expanded?'Reduce chart':'Expand chart'}</button>
    </div>
   </div>
   <p className={styles.comparison}><strong>{comparison.headline}</strong> {comparison.sentence} This comparison alone does not measure risk or time invested.</p>
   <Text as="p" size={11} tone="secondary" className={styles.disclosure}>{engineDisclosure}</Text>
   <div className={styles.legend}>
    <label className={styles.legendItem}><input type="checkbox" checked={show.strategy} onChange={e=>{const on=e.target.checked;setShow(s=>({...s,strategy:on}));}}/><span className={styles.swatchStrategy} aria-hidden="true"/><span>Strategy equity</span>{' '}<Data size={13} tone="accent">{formatPerformance(legend.strategy,unit)}</Data></label>
    <label className={styles.legendItem}><input type="checkbox" checked={show.benchmark} onChange={e=>{const on=e.target.checked;setShow(s=>({...s,benchmark:on}));}}/><span className={styles.swatchBenchmark} aria-hidden="true"/><span>Long buy-and-hold (gross; excludes fees)</span>{' '}<Data size={13}>{formatPerformance(legend.benchmark,unit)}</Data></label>
    <Data size={11} tone="secondary" className={styles.readout}>{readout}</Data>
   </div>
   <Text as="p" size={11} tone="secondary" className={styles.axisTitle}>{unit==='percent'?'Cumulative return (%) · recorded baseline of 100 shown as 0%':'Equity index · recorded baseline is 100'}</Text>
   <div ref={performanceRef} aria-label="Indexed equity comparison" className={expanded?styles.performanceExpanded:styles.performance}/>
   {!performanceAvailable&&<Text as="p" size={12} tone="secondary" className={styles.empty}>Indexed equity is unavailable for this run; the recorded engine summary above remains inspectable.</Text>}
   {performanceAvailable&&!show.strategy&&!show.benchmark&&<Text as="p" size={12} tone="secondary" className={styles.empty}>Both curves are hidden. Select a series above to display it.</Text>}
   <div className={styles.drawdownTitle}>
    <Text size={11} tone="secondary">Sampled strategy drawdown · decline from its previous equity peak</Text>
    <Data size={11} tone="secondary">{drawdown?`Latest ${formatSigned(drawdownNow.latest)}% · deepest sampled ${formatSigned(drawdownNow.deepest)}%`:'Unavailable'}</Data>
   </div>
   {drawdown
    ?<div ref={drawdownRef} aria-label="Sampled strategy drawdown" className={styles.drawdown}/>
    :<Text as="p" size={12} tone="secondary" className={styles.empty}>Sampled drawdown unavailable: it needs a positive recorded starting equity and finite equity samples. The engine max drawdown above is unaffected.</Text>}
   <Text as="p" size={11} tone="secondary" className={styles.caption}>{range==='year'&&yearBounds?`Showing the last UTC calendar year to ${utc(yearBounds.to)}.`:'Showing all recorded history.'} Baseline is unchanged; summary cards describe the full period.</Text>
   <details className={styles.help}>
    <summary><Text size={12} tone="secondary">How do I read these curves?</Text></summary>
    <Text as="p" size={12} tone="secondary">The accent line follows the recorded strategy equity, including open positions at their recorded value and the recorded commission. The dashed line is the recorded long buy-and-hold benchmark of the same underlying, gross of fees, for either strategy direction. Both start from the engine&apos;s recorded index of 100, shown as 0% in Return %. A value of +20% means 100 has become 120. Hide either curve to inspect the other on the same scale. The lower pane shows how far the sampled strategy equity sits below its own previous peak, starting from the recorded initial equity; it is computed from the recorded samples and is separate from the engine max drawdown. Last year and All history change only the visible dates. Price is shown separately below because it uses different units.</Text>
   </details>
  </section>
  <div ref={priceRef} aria-label="Historical candles" className={styles.price}/>
  {detail.trades.length===0&&<p>Successful result: zero closed trades. The recorded equity and benchmark remain visible.</p>}
  <h2>Closed trades</h2>
  <ul>{detail.trades.map(t=><li key={t.id}><button onClick={()=>setSelected(t.id)} aria-label={`Inspect trade ${t.id}`}>{t.id} · {t.direction} · {utc(t.entry_time)} · {t.net_return_pct}% net</button></li>)}</ul>
  {trade&&<section aria-label="Trade inspector" aria-live="polite"><h3>Trade {trade.id}</h3><dl>
   <dt>Direction</dt><dd>{trade.direction}</dd><dt>Entry (UTC)</dt><dd>{utc(trade.entry_time)}</dd><dt>Actual entry fill</dt><dd>{trade.entry_price}</dd>
   <dt>Exit (UTC)</dt><dd>{utc(trade.exit_time)}</dd><dt>Actual exit fill</dt><dd>{trade.exit_price}</dd>
   <dt>Recorded exit reason</dt><dd>{trade.exit_reason==='unknown'?'Unknown (not recorded by engine)':trade.exit_reason}</dd>
   <dt>Net return (%)</dt><dd>{trade.net_return_pct}</dd><dt>Size</dt><dd>{trade.size}</dd><dt>Commission</dt><dd>{trade.commission}</dd>
  </dl></section>}
  <h2>Open positions</h2>
  <p>Equity includes mark-to-market of open positions; closed-trade counts exclude them. No exit is assumed.</p>
  {detail.open_positions.length===0?<p>No recorded open positions.</p>:<ul>{detail.open_positions.map(p=><li key={p.id}>{p.id} · {p.direction} · Entry {utc(p.entry_time)} @ {p.entry_price} · Size {p.size} · Unrealized P&amp;L {p.unrealized_pnl}</li>)}</ul>}
  {fillEvents(detail).some(f=>f.candleTime===null)&&<p>Some fills have no exact original candle timestamp. Their recorded timestamps and prices remain in the inspector; no marker is snapped to another session.</p>}
  <details><summary>Recorded configuration and provenance</summary><p>Provenance: {artifact.provenance} · Artifact {artifact.artifact_id} · Run {identity.scan_id} · Created {utc(artifact.created_at)}</p>
   <p>Evaluation: {detail.candles.length?`${utc(detail.candles[0].time)} — ${utc(detail.candles[detail.candles.length-1].time)}`:'Unavailable'}.</p>
   <p>Strategy commission: {detail.configuration.commission} ({detail.configuration.commission_basis}). Benchmark is gross and excludes fees. Currency was not recorded.</p>
   <h3>Full recorded engine configuration</h3><pre>{JSON.stringify(detail.configuration,null,2)}</pre>
   <h3>Effective strategy parameters</h3><pre>{JSON.stringify(detail.effective_params,null,2)}</pre>
   <h3>Run identity</h3><pre>{JSON.stringify(identity,null,2)}</pre><h3>Recorded summary</h3><pre>{JSON.stringify(detail.summary,null,2)}</pre>
  </details>
 </section>;
}

/** Navigation changes discard the pane; they never execute a backtest. */
export default function CandidateBacktestWorkspace({artifact}:{artifact:BacktestArtifact}) {
 return <EvidenceScope key={artifact.artifact_id} artifact={artifact}/>;
}
function EvidenceScope({artifact}:{artifact:BacktestArtifact}) {
 const [symbol,setSymbol]=useState(artifact.identity.symbol);
 const [interval,setInterval]=useState<string>(artifact.identity.interval);
 const compatible=symbol===artifact.identity.symbol&&interval===artifact.identity.interval;
 return <div className={styles.scope}>
  <nav className={styles.navigation} aria-label="Evidence navigation">
   <label>Symbol <input aria-label="Evidence symbol" value={symbol} onChange={e=>setSymbol(e.target.value.trim().toUpperCase())}/></label>
   <label>Interval <select aria-label="Evidence interval" value={interval} onChange={e=>setInterval(e.target.value)}>
    <option value="1d">1D</option><option value="15m">15min</option><option value="1h">1h</option><option value="1w">1W</option>
   </select></label>
   <a href={`/chart?symbol=${encodeURIComponent(symbol)}`}>Open live chart and overlays</a>
  </nav>
  {compatible?<Evidence artifact={artifact}/>:<p role="status">{artifact.provenance==='fresh'?'Fresh':'Original'} evidence hidden: the selected symbol or interval differs from this recorded run. No backtest was rerun. Restore the recorded symbol and interval to inspect its frozen evidence.</p>}
 </div>;
}
