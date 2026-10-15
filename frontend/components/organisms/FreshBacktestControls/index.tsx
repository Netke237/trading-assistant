'use client';
import {useEffect,useMemo,useRef,useState} from 'react';
import {api} from '@/lib/api';
import type {BacktestArtifact,FreshBacktestConfiguration,FreshBacktestRequest} from '@/types/backtest';
import styles from './FreshBacktestControls.module.css';

interface Props {symbol:string; original:BacktestArtifact|null; onResult:(artifact:BacktestArtifact)=>void;}
const supported=['pullback_ema','breakout_base','ma_crossover','mean_reversion_rsi','mean_reversion_bb','mean_reversion_multi'];
const sizing={initial_cash:100000,order_size:.9999999999999998,margin:1,spread:0,exclusive_orders:true,
 trade_on_close:false,finalize_trades:false,sizing:'fraction of available equity; whole units'} as const;

function canonical(value:unknown):string {
 if(Array.isArray(value))return `[${value.map(canonical).join(',')}]`;
 if(value&&typeof value==='object')return `{${Object.entries(value).sort(([a],[b])=>a.localeCompare(b)).map(([k,v])=>`${JSON.stringify(k)}:${canonical(v)}`).join(',')}}`;
 return JSON.stringify(value);
}
function matchesRequest(artifact:BacktestArtifact,request:FreshBacktestRequest,original:BacktestArtifact|null):boolean {
 const config=artifact.detail?.configuration;
 return artifact.schema_version===1&&typeof artifact.artifact_id==='string'&&!!artifact.artifact_id&&artifact.artifact_id!==original?.artifact_id&&
  artifact.provenance==='fresh'&&artifact.identity?.symbol===request.symbol&&artifact.identity.strategy===request.strategy&&artifact.identity.direction===request.direction&&artifact.identity.interval==='1d'&&
  artifact.detail?.status==='success'&&canonical(artifact.detail.effective_params)===canonical(request.params)&&
  !!config&&config.entry_start===request.start&&config.entry_end===request.end&&config.commission===request.commission&&config.hold_max_days===request.hold_max_days&&
  config.min_trades===request.min_trades&&config.min_win_rate===request.min_win_rate&&
  Object.entries(sizing).every(([key,value])=>config[key as keyof typeof config]===value);
}

/** Remounting this scope invalidates in-flight results before the next effect. */
export default function FreshBacktestControls(props:Props){
 return <FreshForm key={`${props.symbol}:${props.original?.artifact_id??''}`} {...props}/>;
}
function FreshForm({symbol,original,onResult}:Props){
 const known=original?.detail.configuration;
 const [open,setOpen]=useState(false);
 const [configuration,setConfiguration]=useState<FreshBacktestConfiguration|null>(null);
 const [strategy,setStrategy]=useState(original&&supported.includes(original.identity.strategy)?original.identity.strategy:'');
 const [direction,setDirection]=useState(original?.identity.direction??'');
 const [params,setParams]=useState(original?JSON.stringify(original.detail.effective_params,null,2):'');
 const [start,setStart]=useState(known?.entry_start??'');
 const [end,setEnd]=useState(known?.entry_end??'');
 const [commission,setCommission]=useState(known?.commission?.toString()??'');
 const [hold,setHold]=useState(known?String(known.hold_max_days):'');
 const [minTrades,setMinTrades]=useState(known?.min_trades?.toString()??'');
 const [minWinRate,setMinWinRate]=useState(known?.min_win_rate?.toString()??'');
 const [confirmed,setConfirmed]=useState(false);
 const [status,setStatus]=useState('');
 const [running,setRunning]=useState(false);
 const active=useRef<{controller:AbortController}|null>(null);
 const mounted=useRef(true);
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;active.current?.controller.abort();active.current=null;};},[]);
 useEffect(()=>{
  if(!open||configuration)return;
  const controller=new AbortController();let alive=true;
  api.getFreshBacktestConfiguration(controller.signal).then(c=>{if(alive)setConfiguration(c);}).catch(()=>{if(alive)setStatus('Fresh configuration unavailable. Close and reopen to retry.');});
  return()=>{alive=false;controller.abort();};
 },[open,configuration]);
 const request=useMemo(()=>{
  try{
   if(!supported.includes(strategy)||!['Bullish','Bearish'].includes(direction)||!start||!end||start>=end||commission===''||hold===''||minTrades===''||minWinRate==='')return null;
   const parsed:unknown=JSON.parse(params);
   if(!parsed||typeof parsed!=='object'||Array.isArray(parsed))return null;
   const fee=Number(commission),days=hold==='null'?null:Number(hold),minimum=Number(minTrades),win=Number(minWinRate);
   if(!Number.isFinite(fee)||fee<0||fee>=1||(days!==null&&(!Number.isInteger(days)||days<1))||!Number.isInteger(minimum)||minimum<1||!Number.isFinite(win)||win<0||win>1)return null;
   return {symbol,strategy,direction,params:parsed,start,end,commission:fee,hold_max_days:days,min_trades:minimum,min_win_rate:win,...sizing,confirmed:true} as FreshBacktestRequest;
  }catch{return null;}
 },[symbol,strategy,direction,params,start,end,commission,hold,minTrades,minWinRate]);
 const cancel=()=>{active.current?.controller.abort();active.current=null;setRunning(false);setStatus('Fresh run cancelled. Original evidence is unchanged.');};
 const run=async()=>{
  if(!request||!confirmed||running)return;
  const task={controller:new AbortController()};active.current=task;setRunning(true);setStatus('Running a separate fresh backtest…');
  try{
   const result=await api.runFreshBacktest(request,task.controller.signal);
   if(!mounted.current||active.current!==task)return;
   const a=result.artifact;
   if(result.status==='success'&&a&&matchesRequest(a,request,original)){onResult(a);setStatus('Fresh result ready. Original evidence is unchanged.');}
   else setStatus(`Fresh run unavailable: ${result.status==='success'?'invalid_evidence':result.status}. Original evidence is unchanged.`);
  }catch(error){
   if(mounted.current&&active.current===task)setStatus(`Fresh run unavailable: ${error instanceof Error?error.message:'failed'}. Original evidence is unchanged.`);
  }finally{if(mounted.current&&active.current===task){active.current=null;setRunning(false);}}
 };
 return <section className={styles.controls} aria-label="Fresh backtest configuration">
  <h2>Separate fresh backtest</h2>
  <p>Configure a supported daily Stocks strategy for {symbol}. This creates a new result; it never replaces scan evidence, confidence, gates or trading inputs. Setup strategies are not mapped to Stocks strategies.</p>
  {!open?<button onClick={()=>setOpen(true)}>Configure a fresh run</button>:<>
   <button onClick={()=>{if(running)cancel();setOpen(false);}}>Close configuration</button>
   <fieldset disabled={running||!configuration} onChange={()=>setConfirmed(false)}><legend>Explicit configuration review</legend>
    <label>Fresh strategy<select aria-label="Fresh strategy" value={strategy} onChange={e=>{setStrategy(e.target.value);setParams('');}}><option value="">Choose a supported strategy</option>{(configuration?.strategies??supported).map(s=><option key={s} value={s}>{s}</option>)}</select></label>
    <label>Fresh direction<select aria-label="Fresh direction" value={direction} onChange={e=>setDirection(e.target.value)}><option value="">Choose direction</option><option>Bullish</option><option>Bearish</option></select></label>
    <label>Evaluation start<input aria-label="Evaluation start" type="date" value={start} onChange={e=>setStart(e.target.value)}/></label>
    <label>Evaluation end (exclusive)<input aria-label="Evaluation end (exclusive)" type="date" value={end} onChange={e=>setEnd(e.target.value)}/></label>
    <label>Commission per leg (fraction)<input aria-label="Commission per leg (fraction)" type="number" step="any" value={commission} onChange={e=>setCommission(e.target.value)}/></label>
    <label>Maximum hold days (null for none)<input aria-label="Maximum hold days (null for none)" value={hold} onChange={e=>setHold(e.target.value)}/></label>
    <label>Minimum closed trades<input aria-label="Minimum closed trades" type="number" value={minTrades} onChange={e=>setMinTrades(e.target.value)}/></label>
    <label>Minimum win rate (fraction)<input aria-label="Minimum win rate (fraction)" type="number" step="any" value={minWinRate} onChange={e=>setMinWinRate(e.target.value)}/></label>
    <label>Complete strategy parameters (JSON)<textarea aria-label="Complete strategy parameters (JSON)" rows={12} value={params} onChange={e=>setParams(e.target.value)}/></label>
    <p>Every listed parameter is required. Null means the field must explicitly be null. Unknown keys are rejected. No current settings are filled in.</p>
    {strategy&&<pre aria-label="Required parameter contract">{JSON.stringify(strategy==='mean_reversion_multi'?{variants:'Choose daily variants from contracts below',min_confirmations:'Integer 1 through selected variant count',variant_params:configuration?.parameters}:configuration?.parameters[strategy],null,2)}</pre>}
    <p>Fixed engine sizing: initial cash 100000; order size 0.9999999999999998 of available equity, whole units; margin 1; spread 0; exclusive orders; next-bar execution; no forced closing of open trades. Daily interval. Warmup bars precede the evaluation start. End is exclusive. Engine expectancy threshold remains 0.</p>
   </fieldset>
   <label><input type="checkbox" checked={confirmed} disabled={running||!request} onChange={e=>setConfirmed(e.target.checked)}/>I reviewed the strategy, direction, complete parameters, dates, costs and fixed engine sizing.</label>
   <button disabled={!configuration||!request||!confirmed||running} onClick={run}>Run fresh backtest</button>
   {running&&<button onClick={cancel}>Cancel fresh run</button>}
  </>}
  {status&&<p role="status">{status}</p>}
 </section>;
}
