// Deterministic browser boundary audit. All API and websocket access is mocked.
// Start Next on :3027 with NEXT_PUBLIC_API_URL=http://127.0.0.1:8027.
const { chromium } = require('../../../../../../frontend/node_modules/playwright');
const fs = require('fs');
const path = require('path');
const dir = __dirname;
const regime = {
  overall:'PASS', headline:'Mock metrics PASS; directional OMM Bear', metrics:[],
  omm:{state:'Bear',p_stay:.75,stability:'Stable',regime_age_days:37,avg_regime_duration:4,
    duration_stride_bars:20,transition_row:[.15,.75,.10],state_order:['Bull','Bear','Choppy'],conviction_pct:-60,conviction_label:'Weak conviction'},
  intraday_hmm:{state:'Trending',p_stay:.65,p_transition:[{to:'Choppy',prob:.25},{to:'Mean-reverting',prob:.10}]},
  intraday_hmm_status:'ok',intraday_omm:null,vix_pct_30d:25,vix_pct_252d:2.7,
  hmm_state:'Bear',alignment:'Aligned',regime_direction:'BEAR',conviction_pct:-60,conviction_label:'Weak conviction',
};
async function main() {
  const browser = await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
  const output = {boundary:'All API/WebSocket requests mocked; no provider/backend app launched',browser:browser.version(),regime,modes:[]};
  for (const mode of ['options','stocks','prebreakout']) {
    const context=await browser.newContext({viewport:{width:1600,height:1100}});
    await context.addInitScript(({mode})=>{
      localStorage.setItem('bamendjou-scan-store',JSON.stringify({version:19,state:{screenerMode:mode,activeStrategy:'pullback_ema',context:{universe:'SP500',direction:'Bullish',horizon:'Swing',horizonPreset:'Swing',holdMin:5,holdMax:15}}}));
    },{mode});
    const requests=[],errors=[];
    await context.routeWebSocket('**/*',ws=>ws.close());
    await context.route('**/api/**',async route=>{
      const request=route.request(),url=new URL(request.url());
      requests.push({method:request.method(),path:url.pathname,query:url.search,body:request.postDataJSON()});
      let body=[];
      if(url.pathname==='/api/regime') body=regime;
      else if(url.pathname==='/api/scan') body={scan_id:'AUDIT-MOCK',timestamp:'2026-10-16T10:00:00Z',candidates:[],rejected:[]};
      else if(url.pathname==='/api/stock-scan') body={scan_id:'AUDIT-MOCK-STOCK',timestamp:'2026-10-16T10:00:00Z',candidates:[],rejected:[],pipeline:{}};
      else if(['/api/scan/last','/api/stock-scan/last','/api/stock-scan/last-request'].includes(url.pathname)) return route.fulfill({status:404,contentType:'application/json',body:'{}'});
      else if(url.pathname.includes('status')) body={status:'idle',updated_at:null};
      else if(url.pathname.includes('threshold')) body={};
      await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)});
    });
    const page=await context.newPage();
    page.on('pageerror',e=>errors.push(e.message));
    await page.goto('http://127.0.0.1:3027/screener/step-1-regime');
    const nav=page.getByRole('navigation',{name:'Screener step navigation'});
    await nav.waitFor({timeout:60000});
    await page.waitForFunction(()=>document.querySelector('nav[data-regime]')?.dataset.regime==='REJECT',null,{timeout:30000}).catch(async e=>{
      fs.writeFileSync(path.join(dir,'browser-debug.json'),JSON.stringify({errors,requests,text:await page.locator('body').innerText()},null,2));
      throw e;
    });
    const text=await page.locator('body').innerText();
    const row={mode,step1_combined:await nav.getAttribute('data-regime'),
      expected_step1:'REJECT',units_visible:text.includes('37 bars · avg ≈4 strides of 20 bars'),
      stay_percent_visible:text.includes('75% chance of staying'),hmm_percent_visible:text.includes('65% chance of staying'),
      vix_252_label_visible:text.includes('3th percentile (252-day window)'),page_errors:errors};
    await page.screenshot({path:path.join(dir,`${mode}-step1.png`),fullPage:true});
    await nav.getByRole('button',{name:/Next:/}).click();
    row.step1_next_dialog=await page.getByRole('dialog').isVisible();
    await page.getByRole('button',{name:'Proceed anyway →',exact:true}).click();
    await page.waitForURL('**/step-2-universe');
    await nav.getByRole('button',{name:/Next:/}).click();
    await page.waitForURL('**/step-3-direction');
    await page.getByRole('button',{name:mode==='options'?'Run scan':mode==='stocks'?'Run stock scan':'Go to Setup Scanner',exact:true}).click();
    if(mode==='prebreakout') await page.waitForURL('**/step-4-prebreakout');
    await page.waitForTimeout(700);
    row.run_dialog=await page.getByRole('dialog').isVisible();
    row.after_run_url=page.url();
    row.step3_combined=await nav.getAttribute('data-regime');
    row.scan_requests=requests.filter(r=>r.method==='POST'&&(r.path.includes('/scan')||r.path.includes('/stock-scan')));
    row.requests=requests;
    await page.screenshot({path:path.join(dir,`${mode}-run.png`),fullPage:true});
    output.modes.push(row);
    fs.writeFileSync(path.join(dir,'browser-output.json'),JSON.stringify(output,null,2)+'\n');
    await context.close();
  }
  await browser.close();
  console.log(JSON.stringify(output.modes.map(({mode,step1_combined,units_visible,stay_percent_visible,hmm_percent_visible,step1_next_dialog,run_dialog,after_run_url,scan_requests,page_errors})=>({mode,step1_combined,units_visible,stay_percent_visible,hmm_percent_visible,step1_next_dialog,run_dialog,after_run_url,scan_requests,page_errors})),null,2));
}
main().catch(e=>{console.error(e);process.exit(1);});
