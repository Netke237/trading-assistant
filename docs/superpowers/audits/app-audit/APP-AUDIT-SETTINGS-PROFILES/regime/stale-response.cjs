// User navigation leaves an old Step-1 request pending across a later mount.
const {chromium,expect}=require('../../../../../../frontend/node_modules/@playwright/test');
const fs=require('fs'),path=require('path');
const dir=__dirname;
async function main(){
 const browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 const ctx=await browser.newContext({viewport:{width:1600,height:1100}});
 const errors=[],events=[];
 let count=0,releaseOld,phase="old";
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
   await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({overall:'PASS',headline:`Audit ${state}`,metrics:[],omm:{state,p_stay:.8,stability:'Stable',regime_age_days:10,avg_regime_duration:5,duration_stride_bars:20,transition_row:state==='Bear'?[.1,.8,.1]:[.8,.1,.1],state_order:['Bull','Bear','Choppy']},hmm_state:state})});
   events.push({event:'response',id,state});return;
  }
  if(['/api/scan/last','/api/stock-scan/last','/api/stock-scan/last-request'].includes(url.pathname)) return route.fulfill({status:404,body:'{}'});
  await route.fulfill({status:200,contentType:'application/json',body:url.pathname.includes('status')?'{}':'[]'});
 });
 const page=await ctx.newPage();page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:3027/screener/step-1-regime',{waitUntil:'domcontentloaded'});
 await expect.poll(()=>count).toBeGreaterThanOrEqual(1);
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
 const before={verdict:await nav.getAttribute('data-regime'),body:await page.locator('body').innerText()};
 releaseOld();
 await expect(nav).toHaveAttribute('data-regime','REJECT');
 const after={verdict:await nav.getAttribute('data-regime'),body:await page.locator('body').innerText()};
 await nav.getByRole('button',{name:/Next:/}).click();
 const dialog=await page.getByRole('dialog').isVisible();
 await page.screenshot({path:path.join(dir,'stale-response.png'),fullPage:true});
 fs.writeFileSync(path.join(dir,'stale-response-output.json'),JSON.stringify({browser:browser.version(),boundary:'All API and websocket requests mocked; same browser document and actual Next navigation',events,before,after,expected_after:'PASS (latest Bull + Bullish)',actual_after:after.verdict,unexpected_reject_dialog:dialog,errors},null,2)+'\n');
 await browser.close();
 console.log(JSON.stringify({events,expected_after:'PASS',actual_after:after.verdict,unexpected_reject_dialog:dialog,errors}));
}
main().catch(e=>{console.error(e);process.exit(1)});
