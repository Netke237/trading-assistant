'use client';
import {useEffect,useId,useMemo,useRef,useState} from 'react';
import {createChart,CandlestickSeries,BarSeries,LineSeries,createSeriesMarkers,type IChartApi,type ISeriesApi,type ISeriesMarkersPluginApi,type SeriesType,type Time,type AutoscaleInfo,type UTCTimestamp,type MouseEventParams,type SeriesMarker,type PriceFormat} from 'lightweight-charts';
import {useThemeStore} from '@/lib/theme';
import {Text,Data} from '@/components/primitives';
import {Pagination} from '@/components/molecules/Pagination';
import {BacktestTradeTable,type TradeRowView} from '@/components/molecules/BacktestTradeTable';
import type {BacktestArtifact,BacktestTrade} from '@/types/backtest';
import {historicalSeries,fillEvents,utc} from './chart';
import {performanceSeries,performanceSummary,performanceComparison,sampledDrawdown,legendReadout,drawdownReadout,displayBounds,exactSample,formatValue,formatSigned,formatPerformance,tradePage,pageOfTrade,tradeWindow,exitReasonLabel,formatUtcMinute,type PerformanceUnit,type TimeBounds,type TradeSortKey} from './presentation';
import {linkPanes,type LinkedPane} from './paneSync';
import styles from './CandidateBacktestWorkspace.module.css';

type DisplayRange='all'|'year';
type PriceStyle='candles'|'bars'|'line';
type TradeOrder='oldest'|'newest'|'best'|'worst';
interface Visibility {strategy:boolean;benchmark:boolean}
/** Imperative display hooks into the live chart instances; none of them recreates a chart or touches evidence. */
interface PerformanceView {unit(unit:PerformanceUnit):void;visibility(show:Visibility):void;range(range:DisplayRange):void;bounds(bounds:TimeBounds):void;height(expanded:boolean):void;priceStyle(style:PriceStyle):void;markers():void;restyle():void}

const PRICE_STYLES:{style:PriceStyle;label:string}[]=[{style:'candles',label:'Candles'},{style:'bars',label:'OHLC bars'},{style:'line',label:'Line'}];
const ORDERS:Record<TradeOrder,{label:string;key:TradeSortKey;direction:'asc'|'desc'}>={
 oldest:{label:'Oldest first',key:'entry_time',direction:'asc'},
 newest:{label:'Newest first',key:'entry_time',direction:'desc'},
 best:{label:'Highest net return first',key:'net_return_pct',direction:'desc'},
 worst:{label:'Lowest net return first',key:'net_return_pct',direction:'asc'},
};
const TRADE_PAGE_SIZE=6;
const GUIDANCE='Select “Inspect” in the trade table or click a chart marker to connect a trade with the price history.';

const PERFORMANCE_HEIGHT=320,EXPANDED_HEIGHT=520,DRAWDOWN_HEIGHT=130;
const percentFormat:PriceFormat={type:'custom',minMove:0.01,formatter:(value:number)=>`${value.toFixed(2)}%`};
const indexFormat:PriceFormat={type:'price',precision:2,minMove:0.01};
const timed=<T extends {time:number}>(rows:readonly T[])=>rows.map(r=>({...r,time:r.time as UTCTimestamp}));
const percentText=(value:number|null|undefined)=>{const text=formatValue(value);return text==='Unavailable'?text:`${text}%`;};
/** Readable row values only; the inspector keeps every recorded value at full precision. */
const tradeRow=(t:BacktestTrade):TradeRowView=>({
 id:t.id,label:`Trade #${t.id} · ${t.direction}`,entry:formatUtcMinute(t.entry_time),exit:formatUtcMinute(t.exit_time),
 prices:`${formatValue(t.entry_price)} / ${formatValue(t.exit_price)}`,
 // The engine's recorded net return: never recomputed from the fills (shorts and commission matter).
 returnText:formatPerformance(t.net_return_pct,'percent'),
 returnTone:!Number.isFinite(t.net_return_pct)||t.net_return_pct===0?'primary':t.net_return_pct>0?'pass':'reject',
 reason:exitReasonLabel(t.exit_reason),
});
const markerText=(marked:boolean)=>marked?'Marked at the exact candle':'Not marked: no candle has this exact timestamp';

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
 const [priceStyle,setPriceStyle]=useState<PriceStyle>('candles');
 const [markersOn,setMarkersOn]=useState(true);
 // A trade selection may temporarily override the broad range; Clear returns to `range`.
 const [zoomed,setZoomed]=useState(false);
 const [order,setOrder]=useState<TradeOrder>('oldest');
 const [page,setPage]=useState(0);
 const [hoveredFill,setHoveredFill]=useState<string|null>(null);
 const theme=useThemeStore(s=>s.theme);
 const titleId=useId(),priceTitleId=useId(),tradesTitleId=useId(),orderId=useId();
 const curves=useMemo(()=>({percent:performanceSeries(detail,'percent'),index:performanceSeries(detail,'index')}),[detail]);
 const drawdown=useMemo(()=>sampledDrawdown(detail),[detail]);
 const fills=useMemo(()=>fillEvents(detail),[detail]);
 const view=useRef<PerformanceView|null>(null);
 const trade=detail.trades.find(t=>t.id===selected);
 const zoomBounds=zoomed&&trade?tradeWindow(detail,trade):null;
 // Latest display choices, read when the charts are (re)built so a rebuild keeps the view.
 const display=useRef({unit,range,show,expanded,priceStyle,markersOn,selected,zoomBounds});
 display.current={unit,range,show,expanded,priceStyle,markersOn,selected,zoomBounds};
 const inspectButtons=useRef(new Map<string,HTMLButtonElement|null>());
 const focusAfterClear=useRef<string|null>(null);
 /** Pointer (marker click) and keyboard (Inspect button) share this one path. Unknown ids change nothing. */
 const inspect=(id:string)=>{
  const found=detail.trades.find(t=>t.id===id);
  if(!found)return;
  setSelected(id);setZoomed(true);
  const {key,direction}=ORDERS[order];
  const holding=pageOfTrade(detail.trades,key,direction,TRADE_PAGE_SIZE,id);
  if(holding!==null)setPage(holding);
  const bounds=tradeWindow(detail,found);
  if(bounds)view.current?.bounds(bounds);
 };
 const inspectRef=useRef(inspect);
 inspectRef.current=inspect;
 const clearSelection=()=>{
  if(selected===null)return;
  focusAfterClear.current=selected;
  setSelected(null);setZoomed(false);
  view.current?.range(range);
 };
 const chooseRange=(next:DisplayRange)=>{setZoomed(false);setRange(next);view.current?.range(next);};
 const chooseOrder=(next:TradeOrder)=>{
  setOrder(next);
  const holding=selected===null?null:pageOfTrade(detail.trades,ORDERS[next].key,ORDERS[next].direction,TRADE_PAGE_SIZE,selected);
  setPage(holding??0);
 };
 useEffect(()=>{
  if(!priceRef.current||!performanceRef.current)return;
  const chartOptions={timeScale:{timeVisible:true,secondsVisible:true},rightPriceScale:{minimumWidth:80}};
  const price=createChart(priceRef.current,{...chartOptions,height:360});
  const performance=createChart(performanceRef.current,{...chartOptions,height:display.current.expanded?EXPANDED_HEIGHT:PERFORMANCE_HEIGHT});
  const drawdownChart=drawdown&&drawdownRef.current?createChart(drawdownRef.current,{...chartOptions,height:DRAWDOWN_HEIGHT}):null;
  const charts:IChartApi[]=[price,performance,...(drawdownChart?[drawdownChart]:[])];
  const data=historicalSeries(detail);
  // The price series is replaced on a style change; markers and pane sync always follow the active one.
  let style:PriceStyle=display.current.priceStyle;
  // A visible marker whose fill lies outside the plotted values (e.g. an open-price fill in Line mode) widens the scale instead of vanishing.
  const autoscaleInfoProvider=(original:()=>AutoscaleInfo|null):AutoscaleInfo|null=>{
   const base=original();
   if(!base?.priceRange||!display.current.markersOn)return base;
   const visible=price.timeScale().getVisibleRange();
   const from=visible?Number(visible.from):-Infinity,to=visible?Number(visible.to):Infinity;
   let {minValue,maxValue}=base.priceRange;
   for(const f of fills)if(f.candleTime!==null&&f.candleTime>=from&&f.candleTime<=to&&Number.isFinite(f.price)){minValue=Math.min(minValue,f.price);maxValue=Math.max(maxValue,f.price);}
   return {...base,priceRange:{minValue,maxValue}};
  };
  const addPrice=(next:PriceStyle):ISeriesApi<SeriesType>=>{
   if(next==='line'){const line=price.addSeries(LineSeries,{lineWidth:2,autoscaleInfoProvider});line.setData(timed(data.candles.map(c=>({time:c.time,value:c.close}))));return line;}
   const ohlc=next==='bars'?price.addSeries(BarSeries,{autoscaleInfoProvider}):price.addSeries(CandlestickSeries,{autoscaleInfoProvider});
   ohlc.setData(timed(data.candles));return ohlc;
  };
  let priceSeries=addPrice(style);
  // One shared right scale: both curves are in the same units, never dual-scaled.
  const strategy=performance.addSeries(LineSeries,{title:'Strategy equity',priceScaleId:'right',priceFormat:percentFormat});
  const benchmark=performance.addSeries(LineSeries,{title:'Long buy-and-hold (gross; excludes fees)',priceScaleId:'right',lineStyle:2,priceFormat:percentFormat});
  const drawdownSeries=drawdownChart?drawdownChart.addSeries(LineSeries,{title:'Sampled drawdown',priceFormat:percentFormat}):null;
  if(drawdownSeries&&drawdown)drawdownSeries.setData(timed(drawdown));
  const token=(name:string)=>getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  // Compact markers at exact recorded fills on exact candle timestamps only; off-candle fills are never snapped.
  const markerPoints=():SeriesMarker<Time>[]=>{
   const {markersOn:on,selected:chosen}=display.current;
   if(!on)return [];
   const accent=token('--accent'),muted=token('--text-secondary');
   return fills.filter(f=>f.candleTime!==null).map(f=>({id:f.id,time:f.candleTime as UTCTimestamp,position:'atPriceMiddle',price:f.price,
    shape:f.kind==='exit'?'square':f.direction==='Bearish'?'arrowDown':'arrowUp',color:f.kind==='entry'?accent:muted,
    size:f.source==='trade'&&f.tradeId===chosen?1.6:0.8}));
  };
  let markers:ISeriesMarkersPluginApi<Time>=createSeriesMarkers(priceSeries,markerPoints());
  const stylePrice=()=>{
   const pass=token('--pass'),reject=token('--reject');
   if(style==='line')priceSeries.applyOptions({color:token('--text-primary')});
   else if(style==='bars')priceSeries.applyOptions({upColor:pass,downColor:reject});
   else priceSeries.applyOptions({upColor:pass,downColor:reject,borderUpColor:pass,borderDownColor:reject,wickUpColor:pass,wickDownColor:reject});
  };
  const restyle=()=>{
   const bg=token('--bg-surface'),text=token('--text-secondary'),grid=token('--border-subtle'),accent=token('--accent'),reject=token('--reject');
   for(const chart of charts)chart.applyOptions({layout:{background:{color:bg},textColor:text},grid:{vertLines:{color:grid},horzLines:{color:grid}}});
   stylePrice();
   strategy.applyOptions({color:accent});benchmark.applyOptions({color:text});drawdownSeries?.applyOptions({color:reject});
   markers.setMarkers(markerPoints());
  };
  const hasPerformance=()=>curves.percent.strategy!==null||curves.percent.benchmark!==null;
  const panes:{pane:LinkedPane;hasData:()=>boolean}[]=[];
  const link=(chart:IChartApi,element:HTMLElement,hasData:()=>boolean,sampleAt:LinkedPane['sampleAt'])=>{const pane={chart,element,hasData,sampleAt};panes.push({pane,hasData});};
  link(price,priceRef.current,()=>data.candles.length>0,time=>{const row=exactSample(data.candles,time);return row?{value:row.close,series:priceSeries}:null;});
  link(performance,performanceRef.current,hasPerformance,time=>{
   const {unit:current,show:visible}=display.current;
   for(const [key,series,on] of [['strategy',strategy,visible.strategy],['benchmark',benchmark,visible.benchmark]] as const){
    const rows=curves[current][key];const row=on&&rows?exactSample(rows,time):null;
    if(row)return {value:row.value,series};
   }
   return null;
  });
  if(drawdownChart&&drawdownSeries&&drawdownRef.current&&drawdown)link(drawdownChart,drawdownRef.current,()=>true,time=>{const row=exactSample(drawdown,time);return row?{value:row.value,series:drawdownSeries}:null;});
  const unlink=linkPanes(panes.map(p=>p.pane),(time,objectId)=>{setHover(time);setHoveredFill(typeof objectId==='string'?objectId:null);});
  const applyBounds=(bounds:TimeBounds)=>{
   for(const {pane,hasData} of panes)if(hasData())pane.chart.timeScale().setVisibleRange({from:bounds.from as UTCTimestamp,to:bounds.to as UTCTimestamp});
  };
  const applyRange=(next:DisplayRange)=>{
   const bounds=displayBounds(detail,next);
   if(bounds)applyBounds(bounds);
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
   bounds:applyBounds,
   height:next=>performance.applyOptions({height:next?EXPANDED_HEIGHT:PERFORMANCE_HEIGHT}),
   priceStyle:next=>{
    if(next===style)return;
    // Same recorded timestamps in every style, so the visible bars are kept exactly.
    const keep=price.timeScale().getVisibleLogicalRange();
    markers.detach();
    price.removeSeries(priceSeries);
    style=next;priceSeries=addPrice(next);
    markers=createSeriesMarkers(priceSeries,markerPoints());
    stylePrice();
    if(keep)price.timeScale().setVisibleLogicalRange(keep);
   },
   markers:()=>markers.setMarkers(markerPoints()),
   restyle,
  };
  restyle();
  view.current.unit(display.current.unit);
  view.current.visibility(display.current.show);
  if(display.current.zoomBounds)applyBounds(display.current.zoomBounds);else applyRange(display.current.range);
  // A click on a visible marker (or the candle holding one) inspects that closed trade; open positions have no trade row.
  const click=(p:MouseEventParams)=>{
   if(!display.current.markersOn)return;
   const onChart=fills.filter(f=>f.candleTime!==null);
   const fill=onChart.find(f=>f.id===p.hoveredObjectId)||onChart.find(f=>f.source==='trade'&&f.time===p.time);
   if(fill?.source==='trade')inspectRef.current(fill.tradeId);
  };
  price.subscribeClick(click);
  const sized:{chart:IChartApi;element:HTMLElement}[]=[{chart:price,element:priceRef.current},{chart:performance,element:performanceRef.current},...(drawdownChart&&drawdownRef.current?[{chart:drawdownChart,element:drawdownRef.current}]:[])];
  // Unknown until the first layout, so the initial observation also fits the chosen dates.
  const widths=new Map<HTMLElement,number>();
  const observer=new ResizeObserver(()=>{
   let changed=false;
   for(const {chart,element} of sized){
    const width=element.clientWidth;
    if(widths.get(element)===width)continue;
    widths.set(element,width);chart.applyOptions({width});changed=true;
   }
   // A wider pane keeps its bar spacing, leaving blank space; re-fit every pane to the chosen dates (the
   // selection window or the broad range) after the new width. Only on a width change, so a height-only
   // change or an unrelated re-render never overrides a manual pan or zoom.
   if(!changed)return;
   const {zoomBounds:chosen,range:current}=display.current;
   if(chosen)applyBounds(chosen);else applyRange(current);
  });
  for(const {element} of sized)observer.observe(element);
  return()=>{view.current=null;unlink();observer.disconnect();price.unsubscribeClick(click);markers.detach();for(const chart of charts)chart.remove();setHover(null);setHoveredFill(null);};
 },[detail,curves,drawdown,fills]);
 // Display controls only adjust the existing charts: no rebuild, no run, no evidence change.
 useEffect(()=>{view.current?.unit(unit);},[unit]);
 useEffect(()=>{view.current?.visibility(show);},[show]);
 useEffect(()=>{view.current?.height(expanded);},[expanded]);
 useEffect(()=>{view.current?.priceStyle(priceStyle);},[priceStyle]);
 useEffect(()=>{view.current?.markers();},[markersOn,selected]);
 useEffect(()=>{view.current?.restyle();},[theme]);
 useEffect(()=>{
  if(selected!==null||focusAfterClear.current===null)return;
  inspectButtons.current.get(focusAfterClear.current)?.focus();
  focusAfterClear.current=null;
 },[selected]);
 const {key:orderKey,direction:orderDirection}=ORDERS[order];
 const tradeTable=tradePage(detail.trades,orderKey,orderDirection,page,TRADE_PAGE_SIZE);
 const firstRow=tradeTable.page*TRADE_PAGE_SIZE+1;
 const tradeCount=`${tradeTable.total} trade${tradeTable.total===1?'':'s'}`;
 const hovered=hoveredFill===null?null:fills.find(f=>f.id===hoveredFill&&f.candleTime!==null)??null;
 const hoveredText=!hovered?null:hovered.source==='trade'
  ?`Trade #${hovered.tradeId} · ${hovered.direction} ${hovered.kind} · ${utc(hovered.time)} · recorded fill ${hovered.price} · click to inspect`
  :`Open position #${hovered.tradeId} · ${hovered.direction} entry · ${utc(hovered.time)} · recorded fill ${hovered.price} · no exit recorded`;
 const onChart=(time:number)=>fills.some(f=>f.time===time&&f.candleTime!==null);
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
 // Escape clears a selection from anywhere in the report, matching the Clear selection button.
 const onKeyDown=(event:React.KeyboardEvent)=>{if(event.key==='Escape'&&selected!==null){event.stopPropagation();clearSelection();}};
 return <section className={styles.workspace} aria-label={artifact.provenance==='fresh'?'Fresh backtest evidence':'Original backtest evidence'} onKeyDown={onKeyDown}>
  {/* The page header owns the h1; this keeps the displayed run's own identity. */}
  <h2 className={styles.runTitle}>{identity.symbol} — {runLabel}</h2>
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
     <button type="button" className={pressed(range==='year')} aria-pressed={range==='year'} onClick={()=>chooseRange('year')}>Last year</button>
     <button type="button" className={pressed(range==='all')} aria-pressed={range==='all'} onClick={()=>chooseRange('all')}>All history</button>
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
   <Text as="p" size={11} tone="secondary" className={styles.caption}>{zoomBounds?'Showing the selected trade and surrounding dates.':range==='year'&&yearBounds?`Showing the last UTC calendar year to ${utc(yearBounds.to)}.`:'Showing all recorded history.'} Baseline is unchanged; summary cards describe the full period.</Text>
   <details className={styles.help}>
    <summary><Text size={12} tone="secondary">How do I read these curves?</Text></summary>
    <Text as="p" size={12} tone="secondary">The accent line follows the recorded strategy equity, including open positions at their recorded value and the recorded commission. The dashed line is the recorded long buy-and-hold benchmark of the same underlying, gross of fees, for either strategy direction. Both start from the engine&apos;s recorded index of 100, shown as 0% in Return %. A value of +20% means 100 has become 120. Hide either curve to inspect the other on the same scale. The lower pane shows how far the sampled strategy equity sits below its own previous peak, starting from the recorded initial equity; it is computed from the recorded samples and is separate from the engine max drawdown. Last year and All history change only the visible dates. Price is shown separately below because it uses different units.</Text>
   </details>
  </section>
  <section className={styles.panel} aria-labelledby={priceTitleId}>
   <div className={`${styles.panelHead} ${styles.priceHead}`}>
    <div>
     <Text as="div" size={10} tone="dim" className={styles.eyebrow}>02 / PRICE &amp; EXECUTIONS</Text>
     <h2 id={priceTitleId} className={styles.panelTitle}>Where did the strategy enter and exit?</h2>
     <Text as="p" size={12} tone="secondary" className={styles.subtitle}>Recorded OHLC · entry triangles and exit squares at exact candle timestamps · select a trade to inspect</Text>
    </div>
    <div className={styles.controls} role="group" aria-label="Price display">
     {PRICE_STYLES.map(({style,label})=><button key={style} type="button" className={pressed(priceStyle===style)} aria-pressed={priceStyle===style} onClick={()=>setPriceStyle(style)}>{label}</button>)}
     <span className={styles.separator} aria-hidden="true"/>
     <label className={styles.check}><input type="checkbox" checked={markersOn} onChange={e=>setMarkersOn(e.target.checked)}/><Text size={11} tone="secondary">Trade markers</Text></label>
    </div>
   </div>
   <div className={styles.selection} aria-live="polite">
    {trade
     ?<Text size={12}>{`Trade #${trade.id} · ${trade.direction} · ${formatUtcMinute(trade.entry_time)} → ${formatUtcMinute(trade.exit_time)} · Recorded net return ${formatPerformance(trade.net_return_pct,'percent')} · ${exitReasonLabel(trade.exit_reason)}`}</Text>
     :<Text size={12} tone="secondary">{GUIDANCE}</Text>}
    {trade&&<button type="button" className={styles.toggle} onClick={clearSelection}>Clear selection</button>}
   </div>
   <div ref={priceRef} aria-label="Historical candles" className={styles.price}/>
   <Text as="p" size={11} tone="secondary" className={styles.caption}>{hoveredText??'▲ Long entry · ▼ Short entry · ■ Exit · Markers sit at the recorded fill price on its exact candle. Hover a marker for its fill; click it or use Inspect to select its trade. Dates synchronize with the performance chart. Press Escape to clear a selection.'}</Text>
   {fills.some(f=>f.candleTime===null)&&<Text as="p" size={11} tone="secondary" className={styles.caption}>Some fills have no exact original candle timestamp. Their recorded timestamps and prices remain in the inspector; no marker is snapped to another session.</Text>}
  </section>
  <section className={styles.panel} aria-labelledby={tradesTitleId}>
   <div className={styles.panelHead}>
    <div>
     <Text as="div" size={10} tone="dim" className={styles.eyebrow}>03 / TRADES</Text>
     <h2 id={tradesTitleId} className={styles.panelTitle}>From signals to individual outcomes</h2>
     <Text as="p" size={12} tone="secondary" className={styles.subtitle}>Recorded closed trades of this run. Open positions are listed separately below.</Text>
    </div>
    <div className={styles.controls}>
     <label htmlFor={orderId}><Text size={11} tone="secondary">Order</Text></label>
     <select id={orderId} className={styles.select} value={order} onChange={e=>chooseOrder(e.target.value as TradeOrder)}>
      {(Object.keys(ORDERS) as TradeOrder[]).map(key=><option key={key} value={key}>{ORDERS[key].label}</option>)}
     </select>
    </div>
   </div>
   {detail.trades.length===0&&<p className={styles.caption}>Successful result: zero closed trades. The recorded equity and benchmark remain visible.</p>}
   <BacktestTradeTable rows={tradeTable.rows.map(tradeRow)} selectedId={selected} onInspect={inspect} inspectRef={(id,element)=>{if(element)inspectButtons.current.set(id,element);else inspectButtons.current.delete(id);}}/>
   {tradeTable.total>0&&<div className={styles.tableFooter}>
    <Text size={11} tone="secondary">{`${firstRow}–${firstRow+tradeTable.rows.length-1} of ${tradeCount}`}</Text>
    <Pagination totalItems={tradeTable.total} pageSize={TRADE_PAGE_SIZE} currentPage={tradeTable.page+1} onPageChange={next=>setPage(next-1)}/>
   </div>}
   <Text as="p" size={11} tone="secondary" className={styles.caption}>¹ The engine&apos;s recorded net return for the trade, after its recorded commission and in the trade&apos;s direction. It is not recomputed from the prices shown and is not an account-equity contribution. Prices are rounded here; the inspector shows the full recorded values.</Text>
   {trade&&<section className={styles.inspector} aria-label="Trade inspector" aria-live="polite"><h3>Trade {trade.id}</h3><dl>
    <dt>Direction</dt><dd>{trade.direction}</dd><dt>Entry (UTC)</dt><dd>{utc(trade.entry_time)}</dd><dt>Actual entry fill</dt><dd>{trade.entry_price}</dd>
    <dt>Entry marker</dt><dd>{markerText(onChart(trade.entry_time))}</dd>
    <dt>Exit (UTC)</dt><dd>{utc(trade.exit_time)}</dd><dt>Actual exit fill</dt><dd>{trade.exit_price}</dd>
    <dt>Exit marker</dt><dd>{markerText(onChart(trade.exit_time))}</dd>
    <dt>Recorded exit reason</dt><dd>{exitReasonLabel(trade.exit_reason)}</dd>
    <dt>Net return (%)</dt><dd>{trade.net_return_pct}</dd><dt>Size</dt><dd>{trade.size}</dd><dt>Commission</dt><dd>{trade.commission}</dd>
   </dl></section>}
  </section>
  <h2>Open positions</h2>
  <p>Equity includes mark-to-market of open positions; closed-trade counts exclude them. No exit is assumed.</p>
  {detail.open_positions.length===0?<p>No recorded open positions.</p>:<ul>{detail.open_positions.map(p=><li key={p.id}>{p.id} · {p.direction} · Entry {utc(p.entry_time)} @ {p.entry_price} · Size {p.size} · Unrealized P&amp;L {p.unrealized_pnl}</li>)}</ul>}
  <details className={styles.supporting}><summary>Calculation basis &amp; comparison limits</summary>
   <p><strong>Equity:</strong> Strategy equity is the recorded engine equity, including the recorded unrealized value of open positions and the recorded strategy commission of {detail.configuration.commission}{detail.configuration.commission_basis?` (${detail.configuration.commission_basis})`:''}. It is not a cumulative sum of closed-trade returns.</p>
   <p><strong>Benchmark:</strong> Buy-and-hold is the recorded long benchmark of the same underlying, gross and excluding fees, for either strategy direction. No dividend, reinvestment, cash-interest or allocation assumption is added by this view, and no currency was recorded.</p>
   <p><strong>Drawdown:</strong> Sampled drawdown is 100 × (equity ÷ running peak − 1) over every recorded equity sample, with the peak starting at the recorded initial equity of {Number.isFinite(detail.initial_equity)?detail.initial_equity:'Unavailable'}.{drawdown?'':' It is unavailable for this run.'} The engine max drawdown of {Number.isFinite(detail.summary.max_drawdown_pct)?`${detail.summary.max_drawdown_pct}%`:'Unavailable'} is the engine&apos;s own metric and is shown unchanged.</p>
   <p><strong>Display ranges:</strong> Last year, All history and trade selection change only the visible dates, never the test period, baseline or starting capital.</p>
  </details>
  <details className={styles.supporting}><summary>Recorded configuration and provenance</summary><p>Provenance: {artifact.provenance} · Artifact {artifact.artifact_id} · Run {identity.scan_id} · Created {utc(artifact.created_at)}</p>
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
