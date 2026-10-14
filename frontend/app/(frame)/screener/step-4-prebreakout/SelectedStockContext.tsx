'use client';
import {useEffect, useMemo, useState} from 'react';
import {api, type AnalyzeStockRequest, type StockAnalysis} from '@/lib/api';
import {useRiskStore} from '@/lib/riskStore';
import type {PositionCardData, PreBreakoutResultRow, FibPullbackResultRow} from '@/types/stockDomain';
import type {StockExplanation, FundamentalsOut} from '@/types/domain';
import {FundamentalHealthCard} from '@/components/molecules/FundamentalHealthCard';
import {Text, Data} from '@/components/primitives';
import {StatusBadge} from '@/components/atoms/StatusBadge';
import {safetyFlagTooltip} from '@/lib/statusTooltips';
import {toneForStatus} from '@/lib/status';
import type {ScanSnapshot, ScanMode} from './scanThresholds';
import styles from './page.module.css';

type Row = PositionCardData | PreBreakoutResultRow | FibPullbackResultRow;
type Live = {request: AnalyzeStockRequest; data: StockAnalysis; fetchedAt: string};
function supportedFundamentals(f: StockAnalysis['fundamentals']): f is FundamentalsOut {
 return !!f && ['Strong','Neutral','Weak'].includes(f.quality_label) && ['Low','Medium','High'].includes(f.risk_label);
}
interface Context {row: Row | null; snapshot?: ScanSnapshot; mode: ScanMode; live: Live | null; reason: string;}
const display = (v: unknown): string => v == null ? 'Unavailable' : typeof v === 'object' ? JSON.stringify(v) : String(v);
function Raw({value, label}: {value: unknown; label: string}) {return <details className={styles.contextDisclosure}><summary>{label}</summary><pre>{JSON.stringify(value, null, 2) ?? 'Unavailable'}</pre></details>;}
function horizonFor(label?: string): AnalyzeStockRequest['horizon'] | null {
 if (!label) return null;
 if (/^intraday\b/i.test(label)) return 'Intraday';
 if (/^swing\b/i.test(label)) return 'Swing';
 if (/^position\b/i.test(label)) return 'Position';
 return null;
}
export function compatibleExplanation(e: StockExplanation | null | undefined, symbol: string, direction: string, horizon: string | null, score: number): StockExplanation | null {
 return e?.version === 1 && e.scoring_mode === 'stock' && e.symbol === symbol && e.direction === direction && horizon != null && e.horizon === horizon && e.score === score ? e : null;
}
/** Request and result-array identities own every visible field, including between render and effect cleanup. */
export function useSelectedStockContext(row: Row | null, mode: ScanMode, scope: object, snapshot?: ScanSnapshot): Context {
 const limits = useRiskStore(s=>s.limits);
 const input = useMemo(()=>{
  const horizon = horizonFor(snapshot?.scope.horizon);
  if (!row) return {reason:'Select a candidate for stock context.', request:null};
  if (!horizon) return {reason:'Captured horizon unavailable — live stock context cannot use current controls as the scan scope.', request:null};
  if (snapshot?.scope.mode !== mode || (row.direction !== 'Bullish' && row.direction !== 'Bearish')) return {reason:'Selected scan scope incompatible.',request:null};
  if (!Number.isFinite(limits.portfolioValue) || limits.portfolioValue <= 0 || !Number.isFinite(limits.maxLossPerTradePct) || limits.maxLossPerTradePct <= 0) return {reason:'Live context unavailable — positive account size and risk must be supplied.',request:null};
  const request:AnalyzeStockRequest={symbol:row.symbol,direction:row.direction,horizon,strategy:'pullback_ema',account_size:limits.portfolioValue,risk_pct:limits.maxLossPerTradePct};
  if (mode==='pullback' && snapshot.pullback) {request.pullback_ema_period=snapshot.pullback.emaPeriod;request.pullback_trend_ema=snapshot.pullback.trendEma;}
  return {request,reason:'Loading separately fetched stock context…'};
 },[row?.symbol,row?.direction,mode,scope,snapshot,limits.portfolioValue,limits.maxLossPerTradePct]);
 const [state,setState]=useState<{identity: typeof input;live:Live|null;reason:string}|null>(null);
 useEffect(()=>{
  let active=true;
  if (!input.request) return;
  const request=input.request;
  setState({identity:input,live:null,reason:input.reason});
  void Promise.resolve().then(()=>active?api.analyzeStock(request):null).then(data=>{
   if (!active || !data) return;
   if (data.symbol!==request.symbol || data.direction!==request.direction) {setState({identity:input,live:null,reason:'Response identity mismatch — stock context unavailable.'});return;}
   setState({identity:input,live:{request,data,fetchedAt:new Date().toISOString()},reason:''});
  }).catch(()=>{if(active)setState({identity:input,live:null,reason:'Separately fetched stock context unavailable — analysis request failed.'});});
  return ()=>{active=false;};
 },[input]);
 return {row,mode,snapshot,live:state?.identity===input?state.live:null,reason:state?.identity===input?state.reason:input.reason};
}
function LiveScope({live}: {live:Live}) {return <><Text size={11} tone="secondary">Separately fetched {live.data.symbol} stock context · {live.request.direction} · requested horizon {live.request.horizon} · supplementary strategy pullback_ema · fetched {live.fetchedAt}. Historical matched setup evidence unavailable from this live analysis.</Text><Raw label="Supplementary analysis request scope" value={live.request}/></>;}
export function SelectedSentimentFundamentals({context:c}: {context:Context}) {
 const original=c.mode==='pullback' && c.row && 'stock_score' in c.row ? c.row : null;
 const supplementarySentiment=!!original && !original.sentiment && !!c.live?.data.sentiment;
 const supplementaryFundamentals=!!original && !original.fundamentals && !!c.live?.data.fundamentals;
 const suppliedSentiment=original?.sentiment??c.live?.data.sentiment;
 const expectedHorizon=original && !supplementarySentiment?horizonFor(c.snapshot?.scope.horizon):c.live?.request.horizon;
 const s=suppliedSentiment && (original && !supplementarySentiment || suppliedSentiment.horizon===expectedHorizon) ? suppliedSentiment : null;
 // Backend conviction_pct already aligns its sign to the requested trade direction.
 const alignedConviction=s?.conviction_pct;
 const sentimentTone=alignedConviction==null?'dim':alignedConviction>=15?'pass':alignedConviction<=-15?'reject':'caution';
 const f=original?.fundamentals??c.live?.data.fundamentals;
 return <section role="region" aria-label="Selected sentiment and fundamentals" className={styles.contextSection}>
  <Text size={13} weight={500}>{c.row?.symbol??'Selected stock'} · Sentiment and Fundamental Health</Text>
  {original?<Text size={11} tone="secondary">Original Pullback scan context · {original.symbol} · {original.direction} · {c.snapshot?.scope.horizon??'Captured horizon unavailable'}</Text>:c.live?<LiveScope live={c.live}/>:<Text size={12} tone="dim">{c.reason}</Text>}
  <div className={styles.contextGrid}>
   <div className={styles.contextCard}><Text size={12} weight={500}>Selected-stock regime sentiment</Text>
    {supplementarySentiment && c.live && <><Text size={11}>Original Pullback sentiment unavailable; supplementary live sentiment follows.</Text><LiveScope live={c.live}/></>}
    {s && !s.insufficient_data ? <><Text size={12} tone={sentimentTone}>{s.state} · {s.conviction_label} · {s.conviction_pct}% conviction</Text><Text size={11}>{s.horizon} · {s.timeframe} · {c.row?.direction} direction · {alignedConviction!=null && alignedConviction>=15?'Supports selected direction':alignedConviction!=null && alignedConviction<=-15?'Opposes selected direction':'Mixed conviction'} · OMM/HMM {s.alignment}</Text><Text size={11}>{s.interpretation}</Text><Raw label="Complete selected-stock sentiment evidence" value={s}/></>:<Text size={12} tone="dim">Selected-stock sentiment unavailable — no compatible measured history.</Text>}
    {original && c.live && <LiveScope live={c.live}/>}
    {c.live && <Text size={11}>Market backdrop (market scope): {c.live.data.market_backdrop ? `${c.live.data.market_backdrop.direction??'Direction unavailable'} · ${c.live.data.market_backdrop.overall} · VIX ${display(c.live.data.market_backdrop.vix)}`:'Unavailable'}</Text>}
   </div>
   <div className={styles.contextCard}><Text size={12} weight={500}>Fundamental Health · {c.row?.symbol??'Select a candidate'}</Text>
    {supplementaryFundamentals && c.live && <><Text size={11}>Original Pullback fundamentals unavailable; supplementary live fundamentals follow.</Text><LiveScope live={c.live}/></>}
    {f?<>{supportedFundamentals(f)?<FundamentalHealthCard f={f} compact/>:<><Data size={18}>{f.score}</Data><Text size={12}>{f.quality_label} quality · {f.risk_label} risk</Text><Text size={11}>Growth {f.growth_score} · Quality {f.quality_score} · Risk {f.risk_score}</Text>{(f.safety_flags??[]).map(flag=><Text key={flag} size={11} tone="caution">{flag.replace(/_/g,' ')} · {safetyFlagTooltip(flag)}</Text>)}</>}<Raw label="Complete fundamental evidence and safety flags" value={f}/></>:<Text size={12} tone="dim">Fundamental Health unavailable — no selected-stock fundamentals supplied.</Text>}
   </div>
  </div>
 </section>;
}
export function SelectedStockScores({context:c, supplementary=false}: {context:Context; supplementary?: boolean}) {
 const original=!supplementary && c.mode==='pullback' && c.row && 'stock_score' in c.row ? c.row : null;
 const source=original??c.live?.data;
 const horizon=original?horizonFor(c.snapshot?.scope.horizon):c.live?.request.horizon??null;
 const e=source?compatibleExplanation(source.stock_explanation,source.symbol,source.direction,horizon,source.stock_score):null;
 const signalKnown=original || c.live?.data.strategy?.strategy==='pullback_ema';
 return <section role="region" aria-label={supplementary?"Supplementary live stock score context":"Selected stock score context"} className={styles.contextSection}>
  <Text size={14} weight={500}>{c.row?.symbol??'Selected stock'} · {supplementary?'Supplementary live stock score context':'Stock score context'}</Text>
  {original?<Text size={11} tone="secondary">Original Pullback PositionCardData evidence · {original.direction} · {c.snapshot?.scope.horizon??'Captured horizon unavailable'}</Text>:c.live?<LiveScope live={c.live}/>:<Text size={12} tone="dim">{c.reason}</Text>}
  {source&&<><Text size={13}>{source.company||'Company unavailable'}</Text><Text size={12}>Price ${display(source.price)} · {source.direction}</Text><Data size={18}>Stock score: {source.stock_score} / 100</Data><StatusBadge status={source.stock_status}/><Text size={11}>Stock score is a filter score. Setup confidence and historical signal confidence are separate.</Text><Text size={12}>Historical signal confidence: {signalKnown?display(source.confidence):'Unavailable'}</Text>{signalKnown&&<Text size={11}>{source.confidence_text??'Historical confidence qualification unavailable'}</Text>}{!signalKnown&&<Text size={11}>Supplementary pullback_ema signal unavailable or incompatible; this does not qualify the selected setup.</Text>}
   {(source.gate_flags??[]).map((g,i)=><Text key={i} size={12} tone={toneForStatus(g.status)}>{g.gate}: {g.status} · {g.detail}</Text>)}
   {!source.gate_flags?.length&&<Text size={11} tone="dim">Recorded gate flags unavailable.</Text>}
   <Text size={11}>Earnings days: {display(source.earnings_days)} · Veto: {display(source.earnings_veto)}</Text>
  </>}
  {e?<><Text size={12}>Scorer status {e.status} · raw status {e.raw_status} · raw total {e.unrounded_score} · returned total {e.score}</Text><Text size={11}>Pass threshold {e.pass_threshold} · Caution threshold {e.caution_threshold} · rounding {e.rounding} · evaluated {e.evaluated_at}</Text></>:<Text size={12} tone="dim">Complete score evidence unavailable — missing or incompatible symbol, direction, horizon or total.</Text>}
  <div className={styles.scoreContextGrid}>{(['trend','pullback','trigger','event','vol'] as const).map(key=>{
   const component=e?.components[key];return <div className={styles.contextCard} key={key} aria-label={`${key==='vol'?'Volatility':key} component`}><Text size={13} weight={500}>{key==='vol'?'Volatility':key[0].toUpperCase()+key.slice(1)}</Text>{component?<><Data size={18}>{component.measured?component.raw_score:'Unmeasured'}</Data><Text size={11}>Status {component.status} · Raw score {component.raw_score} · Measured {String(component.measured)}</Text><Text size={11}>Weight {component.weight} · Contribution {component.contribution}</Text><Raw label={`${key} notes, observations and configuration`} value={component}/></>:<Text size={12} tone="dim">Unavailable — no compatible component evidence.</Text>}</div>;
  })}</div>
  {e&&<><Raw label="Scorer caps and safety explanations" value={e.caps}/><Raw label="Applied gate configuration" value={e.gate_config}/><Raw label="Complete authoritative score evidence" value={e}/></>}
  {source&&<Raw label={original?'Complete original Pullback disclosure':'Complete live score rules and qualification flags'} value={original??{rules:c.live?.data.rules,gate_flags:source.gate_flags,backtest:signalKnown?source.backtest:null,confidence:signalKnown?source.confidence:null,confidence_text:signalKnown?source.confidence_text:null,earnings_days:source.earnings_days,earnings_veto:source.earnings_veto}}/>}
  {original && !e && c.live && <SelectedStockScores context={c} supplementary/>}
 </section>;
}
