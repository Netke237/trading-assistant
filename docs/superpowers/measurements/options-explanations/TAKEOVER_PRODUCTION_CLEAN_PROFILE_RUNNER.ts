import path from 'path';
const repo=process.env.REPO_ROOT||path.resolve(__dirname,'../../../..');
const {chromium}=require(path.join(repo,'frontend/node_modules/playwright'));
const {setupApiMocks,MOCK_SCAN_CANDIDATE,MOCK_OPTION_CHAIN}=require(path.join(repo,'frontend/e2e/fixtures/api-mocks'));
import fs from 'fs';
const out=path.join(repo,'docs/superpowers/measurements/options-explanations');
const symbols=Array.from({length:20},(_,i)=>`SYM${String(i+1).padStart(2,'0')}`);
const rows:any={};
for(const symbol of symbols) rows[symbol]=Array.from({length:10},(_,j)=>{
 const id=`${symbol}|${90+j*2.5}|2025-05-16|C`;
 const exp=structuredClone(MOCK_OPTION_CHAIN[0].explanation!); exp.contract_id=id; exp.weights={liquidity:.25,spread:.25,delta:.2,dte:.15,iv_rank:.15}; exp.unrounded_score=78.25;
 return {...MOCK_OPTION_CHAIN[0],id,symbol,strike:90+j*2.5,volume:500+j*100,price:3.5+j*.2,explanation:exp};
});
const candidates=symbols.map(symbol=>({...MOCK_SCAN_CANDIDATE,symbol,company:`${symbol} Corp`,contract:`${symbol}|100|2025-05-16|C`,contractDetails:{...MOCK_SCAN_CANDIDATE.contractDetails,strike:100}}));
const stats=(a:number[])=>{const b=[...a].sort((x,y)=>x-y);return {runs:a,median:b[2],p95:b[4]}};
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',args:['--no-sandbox']});
 const results:any={browser:browser.version(),fixture:'deterministic20symbols10rows',viewport:{width:1440,height:1000},variants:[]};
 for(const [label,port] of (process.env.BENCH_VARIANT==='baseline' ? [['baseline',3102]] : [['clean_profile',3103]]) as any){
  for(const panels of [200]){
   const runs:any[]=[];
   for(let run=0;run<1;run++){
    const ctx=await browser.newContext({viewport:results.viewport});await ctx.tracing.start({screenshots:false,snapshots:false,sources:false});const page=await ctx.newPage();
    await setupApiMocks(page);const requests:any[]=[];page.on('request',r=>{if(r.url().includes('/api/'))requests.push({url:r.url(),at:Date.now()})});
    await page.route('**/api/contracts?**',async route=>{const u=new URL(route.request().url());const symbol=u.searchParams.get('symbol')!;await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(rows[symbol]||[])});});
    await page.addInitScript(({candidates})=>{
     localStorage.setItem('bamendjou-scan-store',JSON.stringify({version:13,state:{scanResult:{scan_id:'production-benchmark',timestamp:'2026-10-03T12:00:00Z',candidates,rejected:[],contract_rules:{min_volume:20}},context:{direction:'Bullish',horizon:'Swing (5-20d)',holdMin:5,holdMax:20},scanState:'COMPLETED',scanAt:'2026-10-03T12:00:00Z'}}));
     (window as any).__tasks=[];new PerformanceObserver(list=>{for(const e of list.getEntries())(window as any).__tasks.push({start:e.startTime,duration:e.duration})}).observe({entryTypes:['longtask']});
    },{candidates});
    const start=Date.now();await page.goto(`http://localhost:${port}/screener/step-6-contracts`);await page.waitForFunction(()=>document.querySelectorAll('[role="button"][data-status]').length===200);await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));const load=Date.now()-start;
    const initialRequests=requests.filter(r=>r.url.includes('/api/contracts?'));if(initialRequests.length!==20)throw Error(`Expected20 chain calls: ${initialRequests.length}`);
    const prepareStart=await page.evaluate(()=>performance.now());
    if(panels)await page.evaluate(async count=>{for(let i=0;i<count;i++){const buttons=Array.from(document.querySelectorAll<HTMLButtonElement>('button')).filter(b=>b.getAttribute('aria-label')?.startsWith('Explain score'));buttons[0].click();await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));}},panels);
    const mounted=await page.locator('[role="region"][aria-label^="Score explanation"]').count();if(mounted!==panels)throw Error(`Expected${panels} valid mounted explanation regions,got${mounted}`);
    const preparation=await page.evaluate(start=>({duration:performance.now()-start,tasks:(window as any).__tasks.filter((x:any)=>x.start>=start)}),prepareStart);
    const cdp=await ctx.newCDPSession(page);await cdp.send('Profiler.enable');await cdp.send('Profiler.start');await cdp.send('Tracing.start',{categories:'devtools.timeline,v8,blink.user_timing',transferMode:'ReturnAsStream'});const requestWatermark=requests.length; const interactionStart=await page.evaluate(()=>performance.now());const interactions:any={};
    for(const action of ['sort','pick','toggle']){
     interactions[action]=await page.evaluate(async action=>{
      let el:HTMLElement|null=null;if(action==='sort')el=document.querySelector('select[id^="sort-"]');if(action==='pick')el=document.querySelectorAll<HTMLElement>('[role="button"][data-status]')[1];if(action==='toggle')el=Array.from(document.querySelectorAll<HTMLButtonElement>('button')).find(b=>b.getAttribute('aria-label')?.startsWith('Explain score')||b.getAttribute('aria-label')?.startsWith('Hide score'))||null;
      if(!el)throw Error(`No ${action} target`);const start=performance.now();if(action==='sort'){(el as HTMLSelectElement).value='volume';el.dispatchEvent(new Event('change',{bubbles:true}));}else el.click();await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));return performance.now()-start;
     },action);
    }
    const completed=new Promise<any>(resolve=>cdp.once('Tracing.tracingComplete',resolve));await cdp.send('Tracing.end');const trace=await completed;let chunks='';for(;;){const part=await cdp.send('IO.read',{handle:trace.stream});chunks+=part.data;if(part.eof)break;}await cdp.send('IO.close',{handle:trace.stream});fs.writeFileSync(`${out}/TAKEOVER_PRODUCTION_CLEAN_200_DEVTOOLS_TRACE.json`,chunks);const profile=await cdp.send('Profiler.stop');fs.writeFileSync(`${out}/TAKEOVER_PRODUCTION_CLEAN_200_CPU_PROFILE.json`,JSON.stringify(profile));const tasks=await page.evaluate(start=>(window as any).__tasks.filter((x:any)=>x.start>=start),interactionStart);const interactionRequests=requests.slice(requestWatermark); if(interactionRequests.length)throw Error('Interaction API HTTP increase');
    const chainAfter=requests.filter(r=>r.url.includes('/api/contracts?'));if(chainAfter.length!==20)throw Error('Interaction chain HTTP increase');
    runs.push({run,load,mounted,initialChainRequests:initialRequests,allApiRequests:requests,chainAfter:chainAfter.length,interactionHttp:interactionRequests,preparation,interactions,tasks});
    await ctx.tracing.stop({path:`${out}/TAKEOVER_PRODUCTION_${label}_${panels}_${run}.zip`});await ctx.close();
    console.log(label,panels,run,interactions,'longtasks',tasks.filter((t:any)=>t.duration>100));
   }
   results.variants.push({label,panels,runs,stats:{load:stats(runs.map(r=>r.load)),sort:stats(runs.map(r=>r.interactions.sort)),pick:stats(runs.map(r=>r.interactions.pick)),toggle:stats(runs.map(r=>r.interactions.toggle))}});
   fs.writeFileSync(`${out}/TAKEOVER_PRODUCTION_${label}_RESULTS.json`,JSON.stringify(results,null,2));
  }
 }
 await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
