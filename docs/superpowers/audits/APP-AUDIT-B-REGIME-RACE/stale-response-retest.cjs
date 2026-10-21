// APP-AUDIT-B-REGIME-RACE retest of the #386 reproduction
// (docs/superpowers/audits/app-audit/APP-AUDIT-SETTINGS-PROFILES/regime/stale-response.cjs),
// run once per screener mode. Same scenario: Step 1's first /api/regime request (Bear) is held,
// the user goes Step 2 -> Step 1, the newer request answers Bull, then the old one is released.
// Changed from the original: system browser via BROWSER_PATH, BASE_URL, a mode click, and the
// after-state is read after a fixed settle instead of waiting for the (pre-fix) REJECT.
// Usage: BASE_URL=http://127.0.0.1:3027 BROWSER_PATH=<chrome/edge exe> OUT=<file.json> node stale-response-retest.cjs
const {chromium,expect}=require('../../../../frontend/node_modules/@playwright/test');
const fs=require('fs'),path=require('path');
const BASE=process.env.BASE_URL||'http://127.0.0.1:3027';
const OUT=process.env.OUT||path.join(__dirname,'stale-response-retest-output.json');
const MODES=[['options','Options'],['stocks','Stocks'],['prebreakout','Pre-Breakout']];

async function runMode(browser,[mode,label]){
 const ctx=await browser.newContext({viewport:{width:1600,height:1100}});
 const errors=[],events=[];
 let count=0,releaseOld,phase='old';
 const oldWait=new Promise(resolve=>{releaseOld=resolve;});
 await ctx.routeWebSocket('**/*',ws=>ws.close());
 await ctx.route('**/api/**',async route=>{
  const url=new URL(route.request().url());
  if(url.pathname==='/api/regime'){
   const id=++count;
   events.push({event:'request',id});
   const old=phase==='old';
   if(old)await oldWait;
   const state=old?'Bear':'Bull';
   await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({overall:'PASS',headline:`Audit ${state}`,metrics:[],omm:{state,p_stay:.8,stability:'Stable',regime_age_days:10,avg_regime_duration:5,duration_stride_bars:20,transition_row:state==='Bear'?[.1,.8,.1]:[.8,.1,.1],state_order:['Bull','Bear','Choppy']},hmm_state:state})}).catch(()=>{});
   events.push({event:'response',id,state});return;
  }
  if(['/api/scan/last','/api/stock-scan/last','/api/stock-scan/last-request'].includes(url.pathname)) return route.fulfill({status:404,body:'{}'});
  await route.fulfill({status:200,contentType:'application/json',body:url.pathname.includes('status')?'{}':'[]'});
 });
 const page=await ctx.newPage();page.on('pageerror',e=>errors.push(e.message));
 await page.goto(`${BASE}/screener/step-1-regime`,{waitUntil:'domcontentloaded'});
 await expect.poll(()=>count,{timeout:60000}).toBeGreaterThanOrEqual(1);
 await page.getByRole('button',{name:label,exact:true}).click();
 await page.waitForTimeout(500);
 const oldCount=count;
 await page.getByRole('button',{name:'2 Universe',exact:true}).click({noWaitAfter:true});
 await page.waitForURL('**/step-2-universe',{waitUntil:'domcontentloaded'});
 phase='new';
 await page.getByRole('button',{name:'Market Regime',exact:true}).click({noWaitAfter:true});
 await page.waitForURL('**/step-1-regime',{waitUntil:'domcontentloaded'});
 await expect.poll(()=>count).toBeGreaterThan(oldCount);
 const nav=page.getByRole('navigation',{name:'Screener step navigation'});
 await expect(nav).toHaveAttribute('data-regime','PASS');
 const before={verdict:await nav.getAttribute('data-regime'),headline:await page.getByTestId('regime-banner').innerText()};
 releaseOld();
 await expect.poll(()=>events.filter(e=>e.event==='response'&&e.state==='Bear').length).toBeGreaterThanOrEqual(1);
 await page.waitForTimeout(1500);
 const after={verdict:await nav.getAttribute('data-regime'),headline:await page.getByTestId('regime-banner').innerText()};
 await nav.getByRole('button',{name:/Next:/}).click();
 await page.waitForTimeout(500);
 const dialog=await page.getByRole('dialog').isVisible();
 await page.screenshot({path:path.join(path.dirname(OUT),`stale-response-retest-${mode}.png`),fullPage:true});
 await ctx.close();
 return {mode,events,before,after,expected_after:'PASS (latest Bull + Bullish)',actual_after:after.verdict,reject_dialog:dialog,errors};
}

async function main(){
 const browser=await chromium.launch({executablePath:process.env.BROWSER_PATH,headless:true});
 const results=[];
 for(const m of MODES) results.push(await runMode(browser,m));
 const out={browser:browser.version(),base:BASE,boundary:'All API and websocket requests mocked; same browser document and actual Next navigation',results};
 await browser.close();
 fs.writeFileSync(OUT,JSON.stringify(out,null,2)+'\n');
 console.log(JSON.stringify(results.map(r=>({mode:r.mode,before:r.before.verdict,after:r.actual_after,reject_dialog:r.reject_dialog,errors:r.errors.length}))));
}
main().catch(e=>{console.error(e);process.exit(1)});
