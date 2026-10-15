'use client';
import {useEffect,useRef,useState} from 'react';
import {createChart,CandlestickSeries,LineSeries,createSeriesMarkers,type UTCTimestamp,type MouseEventParams,type LogicalRange,type SeriesMarker} from 'lightweight-charts';
import {useThemeStore} from '@/lib/theme';
import type {BacktestArtifact} from '@/types/backtest';
import {historicalSeries,fillEvents,utc} from './chart';
import styles from './CandidateBacktestWorkspace.module.css';

/** Frozen evidence owns its series and never subscribes to quotes or live strategy overlays. */
function Evidence({artifact}:{artifact:BacktestArtifact}) {
 const {detail,identity}=artifact;
 const priceRef=useRef<HTMLDivElement>(null);
 const equityRef=useRef<HTMLDivElement>(null);
 const [selected,setSelected]=useState<string|null>(null);
 const theme=useThemeStore(s=>s.theme);
 const restyle=useRef<(()=>void)|null>(null);
 useEffect(()=>{
  if(!priceRef.current||!equityRef.current)return;
  const price=createChart(priceRef.current,{height:360,timeScale:{timeVisible:true,secondsVisible:true},rightPriceScale:{minimumWidth:80}});
  const equity=createChart(equityRef.current,{height:220,timeScale:{timeVisible:true,secondsVisible:true},rightPriceScale:{minimumWidth:80}});
  const candle=price.addSeries(CandlestickSeries);
  const strategy=equity.addSeries(LineSeries,{title:'Strategy equity (index)',priceFormat:{type:'price',precision:4,minMove:0.0001}});
  const benchmark=equity.addSeries(LineSeries,{title:'Long buy-and-hold (gross; excludes fees)',lineStyle:2});
  const data=historicalSeries(detail);
  const timed=<T extends {time:number}>(rows:T[])=>rows.map(r=>({...r,time:r.time as UTCTimestamp}));
  candle.setData(timed(data.candles));strategy.setData(timed(data.strategy));benchmark.setData(timed(data.benchmark));
  const fills=fillEvents(detail);
  const token=(name:string)=>getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const markers=createSeriesMarkers(candle,[]);
  const updateTheme=()=>{
   const bg=token('--bg-surface'),text=token('--text-secondary'),grid=token('--border-subtle'),accent=token('--accent'),pass=token('--pass'),reject=token('--reject');
   for(const chart of [price,equity])chart.applyOptions({layout:{background:{color:bg},textColor:text},grid:{vertLines:{color:grid},horzLines:{color:grid}}});
   candle.applyOptions({upColor:pass,downColor:reject,borderUpColor:pass,borderDownColor:reject,wickUpColor:pass,wickDownColor:reject});
   strategy.applyOptions({color:accent});benchmark.applyOptions({color:text});
   const points:SeriesMarker<UTCTimestamp>[]=fills.filter(f=>f.candleTime!==null).map(f=>({id:f.id,time:f.candleTime as UTCTimestamp,position:'atPriceMiddle',price:f.price,shape:f.kind==='entry'?'arrowUp':'arrowDown',color:f.kind==='entry'?accent:text,text:`${f.direction} ${f.kind} @ ${f.price}`}));
   markers.setMarkers(points);
  };
  restyle.current=updateTheme;updateTheme();
  let rangeBusy=false,crossBusy=false;
  let lastRangeKey:string|null=null;
  let lastCrossTime:MouseEventParams['time']|null|undefined=undefined;
  const syncRange=(target:typeof price)=>(range:LogicalRange|null)=>{if(!range||rangeBusy)return;const key=`${range.from}:${range.to}`;if(key===lastRangeKey)return;lastRangeKey=key;rangeBusy=true;try{target.timeScale().setVisibleLogicalRange(range);}finally{rangeBusy=false;}};
  const priceRange=syncRange(equity),equityRange=syncRange(price);
  price.timeScale().subscribeVisibleLogicalRangeChange(priceRange);equity.timeScale().subscribeVisibleLogicalRangeChange(equityRange);
  const syncCross=(target:typeof price,source:'price'|'equity')=>(p:MouseEventParams)=>{
   if(crossBusy||p.time===lastCrossTime)return;lastCrossTime=p.time;crossBusy=true;
   try{if(p.time==null){target.clearCrosshairPosition();return;}
    const row=source==='price'?data.strategy.find(r=>r.time===p.time):data.candles.find(r=>r.time===p.time);
    if(row)target.setCrosshairPosition('value' in row?row.value:row.close,p.time,source==='price'?strategy:candle);
    else target.clearCrosshairPosition();
   }finally{crossBusy=false;}
  };
  const priceCross=syncCross(equity,'price'),equityCross=syncCross(price,'equity');
  price.subscribeCrosshairMove(priceCross);equity.subscribeCrosshairMove(equityCross);
  const click=(p:MouseEventParams)=>{const fill=fills.find(f=>f.id===p.hoveredObjectId)||fills.find(f=>f.time===p.time);if(fill)setSelected(fill.tradeId);};
  price.subscribeClick(click);
  price.timeScale().fitContent();equity.timeScale().fitContent();
  const observer=new ResizeObserver(()=>{
   if(priceRef.current)price.applyOptions({width:priceRef.current.clientWidth});
   if(equityRef.current)equity.applyOptions({width:equityRef.current.clientWidth});
  });
  observer.observe(priceRef.current);observer.observe(equityRef.current);
  return()=>{restyle.current=null;observer.disconnect();price.unsubscribeClick(click);price.unsubscribeCrosshairMove(priceCross);equity.unsubscribeCrosshairMove(equityCross);price.timeScale().unsubscribeVisibleLogicalRangeChange(priceRange);equity.timeScale().unsubscribeVisibleLogicalRangeChange(equityRange);markers.detach();price.remove();equity.remove();};
 },[detail]);
 useEffect(()=>{restyle.current?.();},[theme]);
 const trade=detail.trades.find(t=>t.id===selected);
 return <section className={styles.workspace} aria-label="Original backtest evidence">
  <h1>{identity.symbol} — Original backtest</h1>
  <p>{identity.strategy} · {identity.direction} · {identity.horizon} · Original interval: {identity.interval}</p>
  <p>Frozen historical evidence. Live overlays are separate. Time basis: {detail.time_basis}.</p>
  <div ref={priceRef} aria-label="Historical candles" className={styles.price}/>
  <p>Strategy equity (index) · Long buy-and-hold (gross; excludes fees). Both use the original evaluation baseline of 100.</p>
  <div ref={equityRef} aria-label="Indexed equity comparison" className={styles.equity}/>
  <p>Indexed ending change: {detail.equity.length?detail.equity[detail.equity.length-1].strategy_index-100:'Unavailable'}%. Engine total return: {detail.summary.total_return_pct}%. Summary metrics retain engine rounding and definitions.</p>
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
  <details><summary>Recorded configuration and provenance</summary><p>Artifact {artifact.artifact_id} · Scan {identity.scan_id} · Created {utc(artifact.created_at)}</p>
   <p>Evaluation: {detail.candles.length?`${utc(detail.candles[0].time)} — ${utc(detail.candles[detail.candles.length-1].time)}`:'Unavailable'}.</p>
   <p>Strategy commission: {detail.configuration.commission} ({detail.configuration.commission_basis}). Benchmark is gross and excludes fees. Currency was not recorded.</p>
   <h3>Full recorded engine configuration</h3><pre>{JSON.stringify(detail.configuration,null,2)}</pre>
   <h3>Effective strategy parameters</h3><pre>{JSON.stringify(detail.effective_params,null,2)}</pre>
   <h3>Run identity</h3><pre>{JSON.stringify(identity,null,2)}</pre><h3>Original summary</h3><pre>{JSON.stringify(detail.summary,null,2)}</pre>
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
  {compatible?<Evidence artifact={artifact}/>:<p role="status">Original evidence hidden: the selected symbol or interval differs from this recorded run. No backtest was rerun. Restore the original symbol and interval to inspect its frozen evidence.</p>}
 </div>;
}
