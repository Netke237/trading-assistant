import {test, expect, type Page, type Route, type TestInfo} from '../fixtures';
import {createHash} from 'crypto';
import {readFileSync} from 'fs';
import path from 'path';

const modes=[{name:'Pre-Breakout',key:'prebreakout',header:'Setup confidence'},{name:'Pullback to EMA 50',key:'pullback',header:'Historical signal confidence'},{name:'Fib Pullback',key:'fib',header:'Fib proximity confidence'}] as const;
type Mode=typeof modes[number];
const sentiment={horizon:'Swing',timeframe:'Daily',state:'Bull',conviction_label:'Moderate',conviction_pct:17,alignment:'Aligned',interpretation:'Measured selected stock conviction',insufficient_data:false};
const fundamentals={score:58,growth_score:27,quality_score:75,risk_score:74,quality_label:'Strong',risk_label:'Low',safety_flags:[]};
const stock=(symbol:string)=>({symbol,company:`${symbol} Company`,direction:'Bullish',price:123.45,stock_score:82,stock_status:'PASS',confidence:67,strategy:{strategy:'pullback_ema'},sentiment,fundamentals,gate_flags:[],backtest:null});
const rows=(mode:string)=>['AAA','BBB'].map((symbol,i)=>mode==='pullback'?stock(symbol):mode==='fib'?{symbol,direction:'Bullish',confidence:i?0:84,fib_level_hit:'38.2%',fib_dist_pct:i?null:0,at_level:i?null:true,fib_swing:{low:100,high:200}}:{symbol,direction:'Bullish',confidence:i?0:84,metrics:{atr_ratio:i?null:0,range_ratio:2,vol_ratio:.6,proximity_pct:0,current_atr:2,swing_level:150}});
const article=(symbol:string)=>[{id:symbol,symbol,headline:`${symbol} measured headline`,source:'Fixture publisher',timestamp:'2026-11-10T14:00:00Z',url:`https://example.com/${symbol}`}];
const terminal={version:1,resolution_available:true,complete:true,input_symbols:['AAA','BBB'],evaluated_symbols:['AAA','BBB'],unknown_symbols:[],outcomes:['AAA','BBB'].map(symbol=>({symbol,terminal:'accepted',code:'candidate_returned'})),counts:{input:2,evaluated:2,accepted:2,excluded:0,no_data:0,error_count:0,no_setup:0,filtered:0}};
const report=(category:string,request:unknown={})=>({category,run_id:`REF-${category}`,generation:1,trigger:'manual',started_at:'2026-11-10T14:00:00Z',ended_at:'2026-11-10T14:01:00Z',status:'complete',persistence:'saved',inputs:{request,effective_configuration_complete:false},diagnostics_available:true,diagnostics:{terminal_outcomes:terminal},result:{candidates:rows(category)}});
async function prepare(page:Page,theme='dark',state:'ready'|'empty'|'unavailable'|'late'='ready'){
 const counts={scans:0,analysis:0,news:0,candles:0};const forbidden:string[]=[];const held:Array<()=>Promise<void>>=[];const requests:Record<string,unknown>={};
 await page.addInitScript(({theme})=>{
  localStorage.setItem('bamendjou:theme',JSON.stringify({version:0,state:{theme}}));
  localStorage.setItem('bamendjou-scan-store',JSON.stringify({version:19,state:{screenerMode:'prebreakout',scanState:'COMPLETED',context:{universe:'SP500',direction:'Bullish',horizon:'Swing (5-15d)'},preBreakoutResults:[],fibPullbackResults:[]}}));
 },{theme});
 const json=(route:Route,body:unknown,headers?:Record<string,string>)=>route.fulfill({status:200,contentType:'application/json',headers:{'Access-Control-Allow-Origin':route.request().headers().origin??'*','Access-Control-Allow-Credentials':'true','Access-Control-Expose-Headers':'X-Scan-Report-Run-Id, X-Scan-Report-Generation, X-Scan-Report-Persistence',...headers},body:JSON.stringify(body)});
 await page.route('**/api/**',async route=>{
  const req=route.request(),url=new URL(req.url()),p=url.pathname;
  if(['/api/scan/prebreakout','/api/scan/fib-pullback','/api/stock-scan'].includes(p)){
   counts.scans++;const mode=p.endsWith('prebreakout')?'prebreakout':p.endsWith('fib-pullback')?'fib':'pullback';
   requests[mode]=req.postDataJSON();const candidates=state==='empty'?[]:rows(mode);
   await json(route,mode==='pullback'?{candidates,report_run_id:`REF-${mode}`,report_generation:1,report_persistence:'saved'}:candidates,{'X-Scan-Report-Run-Id':`REF-${mode}`,'X-Scan-Report-Generation':'1','X-Scan-Report-Persistence':'saved'});return;
  }
  if(p==='/api/analyze-stock'){
   counts.analysis++;const {symbol}=req.postDataJSON();
   if(state==='late'&&symbol==='AAA'){held.push(()=>json(route,{...stock(symbol),company:'OLD AAA ANALYSIS',stock_score:99}));return;}
   if(state==='unavailable'){await route.fulfill({status:503,body:'Unavailable fixture'});return;}
   await json(route,stock(symbol));return;
  }
  if(p==='/api/news'){
   counts.news++;const symbol=url.searchParams.get('symbols')!;
   if(state==='unavailable'){await route.fulfill({status:503,body:'Unavailable news fixture'});return;}
   if(state==='late'&&symbol==='AAA'){held.push(()=>json(route,[{...article(symbol)[0],headline:'OLD AAA NEWS'}]));return;}
   await json(route,article(symbol));return;
  }
  if(p.startsWith('/api/candles/')){counts.candles++;await json(route,Array.from({length:100},(_,i)=>({time:1704067200+i*86400,open:120+i*.1,high:125+i*.1,low:118+i*.1,close:122+i*.1,volume:1000000})));return;}
  if(p.startsWith('/api/scan-reports/latest/')){const category=p.split('/').pop()!;await json(route,{category,latest_attempt:report(category,requests[category]),previous_report:null});return;}
  if(!['GET','HEAD','OPTIONS'].includes(req.method())){forbidden.push(`${req.method()} ${p}`);await route.fulfill({status:405,body:'Unexpected writes refused'});return;}
  await route.fallback();
 });
 await page.goto('/screener/step-4-prebreakout');
 await expect(page.getByRole('heading',{name:'Setup Scanner'})).toBeVisible();
 return {counts,forbidden,release:async()=>{
  const responses=Promise.all([
   page.waitForResponse(response=>new URL(response.url()).pathname==='/api/analyze-stock' && response.request().postDataJSON().symbol==='AAA'),
   page.waitForResponse(response=>new URL(response.url()).pathname==='/api/news' && new URL(response.url()).searchParams.get('symbols')==='AAA'),
  ]);
  for(const resolve of held)await resolve();await responses;
  await page.evaluate(()=>new Promise<void>(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve()))));
 }};
}
const panel=(page:Page,label:string)=>page.locator('details').filter({has:page.locator(':scope > summary').filter({hasText:label})}).first();
async function chooseMode(page:Page,mode:Mode){await page.locator('[data-presentation="prebreakout-v2"]').getByRole('button',{name:mode.name,exact:true}).click();}
async function runAndSelect(page:Page,symbol='AAA'){
 await page.getByRole('textbox').fill('AAA, BBB');await page.getByRole('button',{name:'Run Scan',exact:true}).click();await page.getByRole('button',{name:`Select ${symbol}`,exact:true}).click();
}
async function sourceReport(testInfo:TestInfo){
 const files=['page.tsx','page.module.css','SelectedStockContext.tsx','SelectedStockNews.tsx','SelectedSetupChart.tsx','PreBreakoutRowDetails.tsx','scanChartLines.ts'];
 const source=Object.fromEntries(files.map(file=>[file,createHash('sha256').update(readFileSync(path.join(process.cwd(),'app/(frame)/screener/step-4-prebreakout',file))).digest('hex')]));
 await testInfo.attach('source-sha256.json',{body:Buffer.from(JSON.stringify(source,null,2)),contentType:'application/json'});
}
for(const mode of modes)for(const width of [1280,1366,1920])for(const theme of ['dark','light']){
 test(`${mode.key} reference flow ${width}px ${theme}`,async({page},testInfo)=>{
  await page.setViewportSize({width,height:1000});const {counts,forbidden}=await prepare(page,theme);await chooseMode(page,mode);
  await expect(page.locator('html')).toHaveAttribute('data-theme',theme);
  await expect(page.getByText(mode.header,{exact:true})).toBeVisible();
  const qualification=panel(page,'Stock Qualification'),parameters=panel(page,'Scan parameters'),news=panel(page,'Stock & industry news');
  for(const disclosure of [qualification,parameters,news])await expect(disclosure).not.toHaveAttribute('open','');
  await runAndSelect(page);await expect(page.getByRole('region',{name:'Selected sentiment and fundamentals'})).toContainText('17% conviction');
  const context=page.getByRole('region',{name:'Selected sentiment and fundamentals'});
  const sentimentBox=await context.getByText('Selected-stock regime sentiment',{exact:true}).boundingBox(),fundamentalBox=await context.getByText('Fundamental Health · AAA',{exact:true}).boundingBox();
  expect(fundamentalBox!.y).toBeGreaterThan(sentimentBox!.y+sentimentBox!.height);
  const runBox=await page.getByRole('button',{name:'Run Scan',exact:true}).boundingBox(),contextBox=await context.boundingBox();expect(contextBox!.y).toBeGreaterThan(runBox!.y);
  const summary=qualification.locator(':scope > summary');await expect(summary).toContainText(mode.key==='pullback'?'Original Pullback':'supplementary pullback_ema');if(mode.key!=='pullback')await expect(summary).toContainText('does not qualify');
  await expect(page.getByText(`Displayed rows: run REF-${mode.key}`,{exact:true})).toBeVisible();
  await expect(page.getByRole('button',{name:'Select AAA',exact:true})).toContainText(mode.key==='pullback'?'67%':'84%');
  await expect(page.getByRole('button',{name:'Select BBB',exact:true})).toContainText(mode.key==='pullback'?'67%':'0%');
  await expect(page.getByRole('region',{name:'Selected setup chart'})).toContainText(mode.key==='pullback'?'Scan price levels unavailable.':'Price lines show scan evidence.');
  await expect.poll(()=>counts.news).toBe(1);const before={...counts};
  await page.screenshot({path:testInfo.outputPath('initial.png'),fullPage:true,animations:'disabled'});
  for(const disclosure of [qualification,parameters,news])await disclosure.locator(':scope > summary').click();
  await expect(page.getByRole('region',{name:'Selected stock score context'})).toContainText('Stock score: 82 / 100');
  await expect(news.getByRole('link',{name:'Original article ↗'})).toHaveAttribute('href','https://example.com/AAA');
  expect(await qualification.evaluate(el=>getComputedStyle(el).display)).not.toBe('flex');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
  expect(counts).toEqual(before);await page.screenshot({path:testInfo.outputPath('expanded.png'),fullPage:true,animations:'disabled'});
  for(const disclosure of [qualification,parameters,news])await disclosure.locator(':scope > summary').click();expect(counts).toEqual(before);
  await page.getByRole('button',{name:'Select BBB',exact:true}).focus();await page.keyboard.press('Enter');await expect(page.getByRole('button',{name:'Select BBB',exact:true})).toHaveAttribute('aria-pressed','true');
  await page.getByRole('button',{name:'Filter breakdown',exact:true}).click();await expect(page.getByRole('heading',{name:`Run REF-${mode.key}`,exact:true})).toBeVisible();
  await expect(page.getByText(`Breakdown for saved run REF-${mode.key} matches the displayed table run.`,{exact:true})).toBeVisible();
  await parameters.locator(':scope > summary').click();await parameters.getByRole('spinbutton').first().fill(mode.key==='prebreakout'?'0.8':'60');
  await expect(page.getByRole('button',{name:'Select BBB',exact:true})).toHaveCount(0);await expect(page.getByRole('heading',{name:`Run REF-${mode.key}`,exact:true})).toBeVisible();await expect(page.getByText('Displayed rows: run identity unavailable for the rows shown',{exact:true})).toBeVisible();await expect(page.getByText(`Snapshot: this breakdown belongs to saved run REF-${mode.key}, not to the rows shown (no table run identified).`,{exact:true})).toBeVisible();expect(counts.scans).toBe(1);expect(forbidden).toEqual([]);
  await sourceReport(testInfo);
 });
}
for(const mode of modes){
 test(`${mode.key} empty results preserve the chart shell`,async({page})=>{
  await page.setViewportSize({width:1366,height:1000});await prepare(page,'dark','empty');await chooseMode(page,mode);await page.getByRole('button',{name:'Run Scan',exact:true}).click();await expect(page.getByText('No results yet — run the scan.',{exact:true})).toBeVisible();await expect(page.getByRole('region',{name:'Selected setup chart'})).toContainText('Select a row');
 });
 test(`${mode.key} unavailable supplementary context preserves original setup`,async({page})=>{
  await page.setViewportSize({width:1366,height:1000});const {counts,forbidden}=await prepare(page,'light','unavailable');await chooseMode(page,mode);await runAndSelect(page);await expect(page.getByRole('region',{name:'Selected sentiment and fundamentals'})).toContainText(mode.key==='pullback'?'Original Pullback scan context':'analysis request failed');
  await panel(page,'Stock Qualification').locator(':scope > summary').click();await expect(page.getByRole('region',{name:'Selected stock score context'})).toContainText(mode.key==='pullback'?'Stock score: 82':'analysis request failed');await panel(page,'Stock & industry news').locator(':scope > summary').click();await expect(page.getByRole('region',{name:'Selected stock news'})).toContainText('Headlines unavailable for AAA — news request failed.');expect(counts.scans).toBe(1);expect(forbidden).toEqual([]);
 });
 test(`${mode.key} late analysis/news never replace selected symbol`,async({page})=>{
  await page.setViewportSize({width:1366,height:1000});const {counts,forbidden,release}=await prepare(page,'dark','late');await chooseMode(page,mode);await runAndSelect(page);await expect.poll(()=>counts.analysis).toBe(1);await expect.poll(()=>counts.news).toBe(1);
  await page.getByRole('button',{name:'Select BBB',exact:true}).click();await panel(page,'Stock Qualification').locator(':scope > summary').click();await panel(page,'Stock & industry news').locator(':scope > summary').click();
  await expect(page.getByRole('region',{name:'Selected stock news'})).toContainText('BBB measured headline');await expect(page.getByRole('region',{name:'Selected stock score context'})).toContainText('BBB Company');await release();
  await expect(page.getByText('OLD AAA NEWS',{exact:true})).toHaveCount(0);await expect(page.getByText('OLD AAA ANALYSIS',{exact:true})).toHaveCount(0);await expect(page.getByRole('button',{name:'Select BBB',exact:true})).toHaveAttribute('aria-pressed','true');expect(forbidden).toEqual([]);
 });
}

test('1200px retains the shared 1280px desktop gate without running a scan',async({page})=>{
 await page.setViewportSize({width:1200,height:1000});const {counts,forbidden}=await prepare(page);
 const gate=page.getByRole('dialog',{name:'Desktop required'});await expect(gate).toBeVisible();await expect(gate).toContainText('1280');await expect(gate).toContainText('Current width: 1200');
 expect(counts.scans).toBe(0);expect(forbidden).toEqual([]);
 await page.setViewportSize({width:1280,height:1000});await expect(gate).toHaveCount(0);await expect(page.locator('[data-presentation="prebreakout-v2"]')).toBeVisible();expect(counts.scans).toBe(0);
});
