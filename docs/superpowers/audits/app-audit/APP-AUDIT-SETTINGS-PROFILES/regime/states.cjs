// Offline state coverage: actual Next UI; every API/WebSocket request intercepted.
const {chromium,expect}=require('../../../../../../frontend/node_modules/@playwright/test');
const fs=require('fs'),path=require('path');
const base={overall:'PASS',headline:'Audit completed response',metrics:[],omm:{state:'Bull',p_stay:.75,stability:'Stable',regime_age_days:37,avg_regime_duration:4,duration_stride_bars:20,transition_row:[.75,.15,.1],state_order:['Bull','Bear','Choppy']},intraday_hmm:null,intraday_omm:null,intraday_hmm_status:'unavailable'};
async function main(){
 const browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 const records=[];
 async function setup(response){
  const ctx=await browser.newContext({viewport:{width:1600,height:1100}}),events=[],errors=[];
  await ctx.routeWebSocket('**/*',ws=>ws.close());
  await ctx.route('**/api/**',async route=>{
   const u=new URL(route.request().url());
   if(u.pathname==='/api/regime'){events.push({query:u.search});return response(route);}
   if(['/api/scan/last','/api/stock-scan/last','/api/stock-scan/last-request'].includes(u.pathname))return route.fulfill({status:404,body:'{}'});
   return route.fulfill({status:200,contentType:'application/json',body:'[]'});
  });
  const page=await ctx.newPage();page.on('pageerror',e=>errors.push(e.message));
  return {ctx,page,events,errors};
 }
 const fulfill=(route,body)=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)});
 let phase='loading',release;const wait=new Promise(r=>release=r);
 const normal=await setup(async route=>{if(phase==='loading')await wait;if(phase==='fail')return route.fulfill({status:503,body:'{}'});return fulfill(route,base)});
 const {page}=normal;await page.goto('http://127.0.0.1:3027/screener/step-1-regime',{waitUntil:'domcontentloaded'});
 const nav=page.getByRole('navigation',{name:'Screener step navigation'}),next=nav.getByRole('button',{name:/Next:/});
 await expect(next).toBeDisabled();records.push({case:'loading',combined:await nav.getAttribute('data-regime'),next_disabled:await next.isDisabled()});
 phase='fail';release();await expect(page.getByRole('button',{name:'Retry',exact:true})).toBeVisible();
 records.push({case:'failed_fresh',combined:await nav.getAttribute('data-regime'),next_disabled:await next.isDisabled(),text:await page.locator('body').innerText()});
 phase='ok';await page.getByRole('button',{name:'Retry',exact:true}).click();await expect(nav).toHaveAttribute('data-regime','PASS');
 records.push({case:'retry_success',combined:await nav.getAttribute('data-regime'),next_disabled:await next.isDisabled()});
 await page.reload({waitUntil:'domcontentloaded'});await expect(nav).toHaveAttribute('data-regime','PASS');
 records.push({case:'same_origin_reload',combined:await nav.getAttribute('data-regime'),events:normal.events,errors:normal.errors});await normal.ctx.close();
 const fallback={...base,intraday_omm:{...base.omm,duration_stride_bars:26,regime_age_days:199}};
 const zero={...base,omm:{...base.omm,p_stay:0,regime_age_days:0,avg_regime_duration:0,duration_stride_bars:0},vix_pct_30d:0,vix_pct_252d:0};
 const cases=[['fallback',fallback,'PASS',/199 bars · avg ≈4 strides of 26 bars/],['insufficient',{...base,omm:null,intraday_hmm_status:'insufficient_data'},'CAUTION',/insufficient history/i],['zero',zero,'PASS',/0 bars · avg ≈0 strides/],['legacy_absent_stride',{...base,omm:{...base.omm,duration_stride_bars:undefined}},'PASS',/37 bars · avg ≈4 strides · Stable/],['unavailable',base,'PASS',/Data unavailable/]];
 for(const [name,body,verdict,visible] of cases){const run=await setup(route=>fulfill(route,body));await run.page.goto('http://127.0.0.1:3027/screener/step-1-regime',{waitUntil:'domcontentloaded'});const n=run.page.getByRole('navigation',{name:'Screener step navigation'});await expect(n).toHaveAttribute('data-regime',verdict);await expect(run.page.locator('body')).toContainText(visible);records.push({case:name,response:body,combined:await n.getAttribute('data-regime'),text:await run.page.locator('body').innerText(),requests:run.events,errors:run.errors});await run.ctx.close();}
 fs.writeFileSync(path.join(__dirname,'states-output.json'),JSON.stringify({browser:browser.version(),boundary:'All API and WebSocket requests mocked. Fresh isolated browser contexts; real Next UI.',records},null,2)+'\n');
 await browser.close();console.log(JSON.stringify(records.map(({case:name,combined,next_disabled,errors})=>({case:name,combined,next_disabled,errors}))));
}
main().catch(e=>{console.error(e);process.exit(1)});
