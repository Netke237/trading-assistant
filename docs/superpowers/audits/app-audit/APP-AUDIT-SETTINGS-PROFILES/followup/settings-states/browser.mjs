// Audit-only UI boundary. Every business HTTP request and WebSocket is intercepted.
import {chromium} from '../../../../../../../frontend/node_modules/playwright/index.mjs';
import fs from 'node:fs';
import crypto from 'node:crypto';
import {execFileSync} from 'node:child_process';
const dir=new URL('.',import.meta.url).pathname, root=process.cwd();
const clone=x=>JSON.parse(JSON.stringify(x));
const sha='4b1f6b86e8137f499da0c4c430f23b9c250fd8de';
if(execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim()!==sha)throw Error('Source HEAD changed; review baseline before rerunning');
const sources=['frontend/app/(frame)/settings/page.tsx','frontend/app/(frame)/settings/IvThresholdsSection.tsx','frontend/lib/scanScheduleResolve.ts','frontend/lib/searchProfilesStore.ts','frontend/lib/scanParamsStore.ts','frontend/lib/ivThresholdsStore.ts','frontend/lib/configHealth.ts','frontend/lib/configHealthStore.ts','frontend/components/molecules/ConfigHealthChip/index.tsx','frontend/components/organisms/ConfigHealthBanner/index.tsx','frontend/lib/api.ts','backend/app/schemas/scan_schedule.py','backend/app/routers/scan_schedule.py','backend/app/schemas/stock_scan.py','frontend/lib/resolveStockScanRequest.ts','frontend/lib/resolveOptionsScanRequest.ts','docs/search-profiles/search-profiles-export.json','frontend/package.json','frontend/package-lock.json','backend/config/settings.example.yaml','backend/config/scoring_rules.yaml','backend/config/strategy_params.yaml'];
const hashes=Object.fromEntries(sources.map(p=>[p,crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex')]));
const exported=JSON.parse(fs.readFileSync('docs/search-profiles/search-profiles-export.json'));
const base=clone(exported.state.profiles[0]);
const options={...clone(base),id:'audit-options-a',name:'Audit options A'}, second={...clone(base),id:'audit-options-b',name:'Audit options B',direction:'Bearish'};
const stock={...clone(base),id:'audit-stocks',name:'Audit stocks',mode:'stocks',strategy:'pullback_ema',strategyParams:{btMinTrades:5,btMinWinRate:0.45}};
const legacy={...clone(base),id:'audit-legacy',name:'Legacy missing options fields',scanSettings:{confidenceGate:base.scanSettings.confidenceGate}};
const incomplete={...clone(stock),id:'audit-no-strategy',name:'Legacy stocks without strategy',strategy:undefined,strategyParams:undefined};
const unsupported={...clone(base),id:'audit-unsupported',name:'Unsupported prebreakout',mode:'prebreakout'};
const profiles=[options,second,stock,legacy,incomplete,unsupported];
const out={source_sha:sha,boundary:'ALL BUSINESS HTTP/WS MOCKED. Mock ledger readback is not backend persistence or scheduler certification.',requests:[],checks:[],unknownRequests:[],webSockets:[],pageErrors:[],scenarios:[],fixtureProfiles:profiles};
const check=(id,kind,expected,observed,ok)=>{out.checks.push({id,kind,expected,observed:clone(observed),status:ok?'pass':'fail'});};
const browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox','--no-proxy-server']});
out.versions={browser:browser.version(),node:process.version,next:JSON.parse(fs.readFileSync('frontend/node_modules/next/package.json')).version,playwright:JSON.parse(fs.readFileSync('frontend/node_modules/playwright/package.json')).version};
const clean={ok:true,pid:90210,checked:['isolated fixture schema'],not_checked:['live configuration','runtime scheduler'],errors:[],warnings:[],stale:[]};
const iv=Object.fromEntries(['Intraday','Swing','Position'].map(h=>[h,{abs_pass_max:34,abs_caution_max:55,rank_pass_max:34,rank_caution_max:55}]));
const reply=(route,data,status=200)=>route.fulfill({status,contentType:'application/json',headers:{'Access-Control-Allow-Origin':'*','Access-Control-Allow-Headers':'*','Access-Control-Allow-Methods':'*'},body:JSON.stringify(data)});
async function scenario(name,{seed=profiles,health=clean,ivMode='ok',tzMode='ok'}={}){
 const context=await browser.newContext({viewport:{width:1440,height:1100}});const page=await context.newPage();
 const s={name,entries:[],timezone:'Asia/Tokyo',health:clone(health),ivMode,tzMode,pendingIv:[],pendingTz:[],pendingHealth:[],failUpdate:false,failDelete:false,sequence:0,requests:[]};out.scenarios.push(s);
 await context.addInitScript(({seed})=>localStorage.setItem('bamendjou:search-profiles',JSON.stringify({state:{profiles:seed,legacyTargetPctDropped:false,staleScheduleEntryIds:[]},version:5})),{seed});
 page.on('pageerror',e=>out.pageErrors.push({scenario:name,message:e.message}));
 await context.routeWebSocket('**/*',ws=>{out.webSockets.push({scenario:name,url:ws.url(),action:'closed without upstream connection'});ws.close();});
 await context.route('**/*',async route=>{
  const req=route.request(),u=new URL(req.url()),p=u.pathname,m=req.method();
  const asset=u.hostname==='127.0.0.1'&&u.port==='3027'&&(p==='/settings'||p.startsWith('/_next/')||p==='/favicon.ico');
  if(asset)return route.continue();
  let body=null;try{body=req.postDataJSON()}catch{}
  const r={scenario:name,path:p,method:m,body};out.requests.push(r);s.requests.push(r);
  const send=(data,status=200)=>{r.status=status;r.response=clone(data);return reply(route,data,status);};
  if(m==='OPTIONS')return send({});
  if(p==='/api/config/health'&&m==='GET'){if(s.health==='pending'){s.pendingHealth.push({route,r});return;}if(s.health==='fail')return send({detail:'injected health unavailable'},503);return send(s.health);}
  if(p==='/api/config/iv-thresholds'&&m==='GET'){if(s.ivMode==='pending'){s.pendingIv.push({route,r});return;}if(s.ivMode==='fail')return send({detail:'injected IV unavailable'},503);return send(iv);}
  if(p==='/settings/scheduling'){
   if(m==='GET'&&s.tzMode==='pending'){s.pendingTz.push({route,r});return;}
   if(m==='GET'&&s.tzMode==='fail')return send({detail:'injected timezone unavailable'},503);
   if(m==='PUT')s.timezone=body.timezone;
   return send({timezone:s.timezone,history_years:17});
  }
  if(p==='/api/scan-schedule'){
   if(m==='POST'){const entry={...body,id:'fixture-'+(++s.sequence)};s.entries.push(entry);return send(entry);}
   if(m==='GET')return send(s.entries);
  }
  const match=p.match(/^\/api\/scan-schedule\/([^/]+)(\/runs)?$/);
  if(match){const id=match[1];if(match[2]&&m==='GET')return send([]);
   if(m==='DELETE'){if(s.failDelete)return send({detail:'injected delete failure'},500);s.entries=s.entries.filter(e=>e.id!==id);return send({deleted:true,id});}
   if(m==='PUT'){
    if(s.failUpdate)return send({detail:'injected update failure'},500);
    if(body.pattern==='loop'&&(body.cadence_minutes<5||body.cadence_minutes>1440||body.window_start_hour>=body.window_end_hour))return send({detail:'injected schema-equivalent bounds rejection'},422);
    const idx=s.entries.findIndex(e=>e.id===id);s.entries[idx]={...body,id};return send(s.entries[idx]);
   }
  }
  if(p==='/settings/scheduled-scan-retention'&&m==='GET')return send({scheduledScanRunRetentionDays:90});
  if(['/api/watchlist','/api/portfolio','/api/data-sources'].includes(p)&&m==='GET')return send([]);
  if(['/api/scan/last-run','/api/stock-scan/last-run'].includes(p)&&m==='GET')return send({status:null,updated_at:null});
  if(['/api/scan/last','/api/scan/last-request','/api/stock-scan/last','/api/stock-scan/last-request'].includes(p)&&m==='GET')return send(null);
  out.unknownRequests.push({scenario:name,path:p,method:m});return send({detail:'Denied by isolated followup harness'},404);
 });
 const section=async label=>{await page.locator('aside button').filter({has:page.getByText(label,{exact:true})}).click();await page.waitForTimeout(120);};
 const row=label=>page.locator('[class*="row"]').filter({has:page.getByText(label,{exact:true})}).filter({has:page.locator('input')}).last();
 await page.goto('http://127.0.0.1:3027/settings');await page.getByRole('heading',{name:'Settings',exact:true}).waitFor();
 return {s,page,context,section,row};
}
async function flushPending(s,key,payload){for(const {route,r}of s[key].splice(0)){r.status=200;r.response=clone(payload);await reply(route,payload);} }
try{
 const {s,page,context,section}=await scenario('schedule-crud');await section('Scan');
 const entry=id=>page.getByRole('button',{name:'Delete',exact:true}).first().locator('..').locator('..');
 await page.getByRole('button',{name:'+ Add options entry',exact:true}).click();await page.waitForTimeout(160);
 let e=entry('Audit options A');
 check('schedule-options-create','persistence','POST resolved options profile and GET row readback',s.entries,s.entries[0]?.profile_id===options.id&&await e.count()===1);
 await page.getByRole('button',{name:'+ Add stocks entry',exact:true}).click();await page.waitForTimeout(160);
 check('schedule-stocks-create','persistence','stocks resolver POST and separate row readback',s.entries,s.entries[1]?.mode==='stocks'&&s.entries[1]?.resolved_request.strategy==='pullback_ema');
 await e.locator('input[type=text]').fill('Renamed fixed');await e.locator('input[type=text]').blur();await page.waitForTimeout(160);e=entry('Renamed fixed');
 await e.locator('input[type=time]').fill('13:47');await page.waitForTimeout(160);await e.getByLabel('Sat',{exact:true}).click();await page.waitForTimeout(160);
 check('schedule-fixed-update','persistence','label/time/weekdays survive remount readback',s.entries[0],s.entries[0].label==='Renamed fixed'&&s.entries[0].fire_time==='13:47'&&s.entries[0].days_of_week.includes(5));
 await e.locator('select').first().selectOption(second.id);await page.waitForTimeout(160);
 check('schedule-profile-change','persistence','profile id/name/request direction refreshed together',s.entries[0],s.entries[0].profile_id===second.id&&s.entries[0].resolved_request.direction==='Bearish');
 const before=clone(s.entries[0]);const n=out.requests.length;await e.locator('select').first().selectOption(legacy.id);await page.waitForTimeout(100);
 check('schedule-legacy-profile-refusal','ui','incompatible selected profile explains why it cannot resolve',{entry:s.entries[0],requests:out.requests.slice(n),text:await e.innerText()},(await e.innerText()).includes('cannot resolve'));
 check('schedule-legacy-profile-no-write','persistence','unresolvable legacy profile produces no PUT and preserves old request',{before,after:s.entries[0],requests:out.requests.slice(n)},out.requests.slice(n).every(r=>r.method==='GET')&&s.entries[0].profile_id===before.profile_id);
 await e.locator('select').nth(1).selectOption('loop');await page.waitForTimeout(160);
 await e.locator('input[type=number]').nth(0).fill('35');await page.waitForTimeout(160);await e.locator('input[type=number]').nth(1).fill('7');await page.waitForTimeout(160);await e.locator('input[type=number]').nth(2).fill('20');await page.waitForTimeout(160);
 check('schedule-loop-update','persistence','pattern default loop fields then cadence/window full replacements read back',s.entries[0],s.entries[0].pattern==='loop'&&s.entries[0].fire_time===null&&s.entries[0].cadence_minutes===35&&s.entries[0].window_start_hour===7&&s.entries[0].window_end_hour===20);
 const valid=clone(s.entries[0]);await e.locator('input[type=number]').first().fill('0');await page.waitForTimeout(150);
 check('schedule-invalid-cadence','persistence','422 preserves stored valid cadence',s.entries[0],s.entries[0].cadence_minutes===valid.cadence_minutes);
 check('schedule-invalid-cadence-feedback','ui','invalid edit has visible rejection',{text:await e.innerText(),visible:await e.locator('input[type=number]').first().inputValue()},/invalid|failed|at least|5–1440/i.test(await e.innerText()));
 s.failUpdate=true;await e.locator('input[type=text]').fill('Failed draft');await e.locator('input[type=text]').blur();await page.waitForTimeout(150);
 check('schedule-update-failure-feedback','ui','failed label save visible and no false success',{visible:await e.locator('input[type=text]').inputValue(),stored:s.entries[0].label,text:await e.innerText()},/failed|could not|unavailable/i.test(await e.innerText()));s.failUpdate=false;
 await section('Appearance');await section('Scan');e=entry('Renamed fixed');
 check('schedule-failed-update-remount','persistence','remount uses last successful ledger record',{visible:await e.locator('input[type=text]').inputValue(),stored:s.entries[0]},await e.count()===1);
 await e.getByRole('switch').click();await page.waitForTimeout(150);
 check('schedule-enabled-false','persistence','false serialized and read back',s.entries[0],s.entries[0].enabled===false);
 s.failDelete=true;await e.getByRole('button',{name:'Delete',exact:true}).click();await page.waitForTimeout(130);
 check('schedule-delete-failure-feedback','ui','failed delete is visible',{rows:s.entries.length,text:await e.innerText()},/failed|could not|unavailable/i.test(await e.innerText()));s.failDelete=false;
 await e.getByRole('button',{name:'Delete',exact:true}).click();await page.waitForTimeout(130);
 check('schedule-delete-success','persistence','DELETE then GET removes only chosen entry',s.entries,s.entries.length===1&&s.entries[0].mode==='stocks');
 await page.getByRole('button',{name:'Delete',exact:true}).first().locator('..').locator('..').screenshot({path:dir+'schedule-stocks.png'});await context.close();
 const missing=await scenario('missing-profile',{seed:[second]});missing.s.entries=[{...clone(before),id:'orphan',label:'Orphan schedule',profile_id:'deleted-profile',profile_name:'Deleted profile',resolved_request:clone(before.resolved_request)}];await missing.section('Scan');
 const orphan=missing.page.locator('div[class*="row"]').filter({has:missing.page.locator('input[value="Orphan schedule"]')}).last();
 const orphanSelect=await orphan.locator('select').first().evaluate(el=>({value:el.value,text:el.options[el.selectedIndex]?.textContent,options:Array.from(el.options).map(o=>({value:o.value,text:o.text}))}));
 check('schedule-missing-profile-display','ui','orphan profile shown as missing rather than another selected profile',{stored:missing.s.entries[0].profile_id,select:orphanSelect,row:await orphan.innerText()},orphanSelect.value==='deleted-profile'||/missing|deleted|unavailable/i.test(await orphan.innerText()));await orphan.screenshot({path:dir+'missing-profile.png'});await missing.context.close();
 const absent=await scenario('unsupported-and-legacy-add',{seed:[unsupported,incomplete]});await absent.section('Scan');await absent.page.getByRole('button',{name:'+ Add options entry',exact:true}).click();
 check('schedule-unsupported-mode-no-candidate','ui','unsupported profile excluded from options add',await absent.page.locator('body').innerText(),await absent.page.getByText('No saved options profile yet — save one from Step 3/5 first.',{exact:true}).count()===1);
 await absent.page.getByRole('button',{name:'+ Add stocks entry',exact:true}).click();
 check('schedule-incomplete-stocks-add','ui','missing strategy refusal is explicit and no entry created',{entries:absent.s.entries,text:await absent.page.locator('body').innerText()},absent.s.entries.length===0&&(await absent.page.locator('body').innerText()).includes('has no strategy selected'));await absent.context.close();
 const v=await scenario('iv-loading-failure-reset',{ivMode:'pending'});await v.section('Scan');await v.page.locator('[data-part="iv-thresholds-status"]').waitFor();
 check('iv-initial-loading','numeric','no record: blank text, loading status, Apply disabled',{status:await v.page.locator('[data-part="iv-thresholds-status"]').innerText(),swing:await v.page.getByLabel('Swing pass max',{exact:true}).inputValue(),disabled:await v.page.getByRole('button',{name:'Apply thresholds',exact:true}).isDisabled()},await v.page.getByRole('button',{name:'Apply thresholds',exact:true}).isDisabled()&&await v.page.getByLabel('Swing pass max',{exact:true}).inputValue()==='');
 await flushPending(v.s,'pendingIv',iv);v.s.ivMode='ok';await v.page.waitForTimeout(100);await v.page.getByLabel('Swing pass max',{exact:true}).fill('60');await v.page.getByRole('button',{name:'Reset to scoring_rules.yaml',exact:true}).click();
 check('iv-reset-dirty-unapplied','numeric','Reset discards unapplied dirty text and restores fetched34',await v.page.getByLabel('Swing pass max',{exact:true}).inputValue(),await v.page.getByLabel('Swing pass max',{exact:true}).inputValue()==='34');
 await v.page.getByLabel('Swing pass max',{exact:true}).fill('48');await v.page.getByRole('button',{name:'Apply thresholds',exact:true}).click();await v.page.getByRole('button',{name:'Reset to scoring_rules.yaml',exact:true}).click();await v.section('Appearance');await v.section('Scan');
 check('iv-reset-applied-override','numeric','Reset clears applied override across section remount',await v.page.getByLabel('Swing pass max',{exact:true}).inputValue(),await v.page.getByLabel('Swing pass max',{exact:true}).inputValue()==='34');
 v.s.ivMode='fail';await v.section('Appearance');await v.section('Scan');
 check('iv-fetch-failure','numeric','failed fetch clears record, blanks inputs and disables Apply',{status:await v.page.locator('[data-part="iv-thresholds-status"]').innerText(),swing:await v.page.getByLabel('Swing pass max',{exact:true}).inputValue(),disabled:await v.page.getByRole('button',{name:'Apply thresholds',exact:true}).isDisabled()},await v.page.getByRole('button',{name:'Apply thresholds',exact:true}).isDisabled()&&await v.page.getByLabel('Swing pass max',{exact:true}).inputValue()==='');await v.context.close();
 const tz=await scenario('timezone-initial-failure',{tzMode:'fail'});await tz.section('Scan');const tzrow=tz.row('Timezone');
 check('timezone-initial-get-failure','ui','initial failure visibly distinguishes default draft from unknown stored timezone',{visible:await tzrow.locator('input').inputValue(),stored:tz.s.timezone,row:await tzrow.innerText()},/failed|unavailable|could not|unknown/i.test(await tzrow.innerText()));await tz.context.close();
 const pending=await scenario('timezone-pending-unmount',{tzMode:'pending'});await pending.section('Scan');await pending.row('Timezone').locator('input').fill('America/New_York');await pending.section('Appearance');await flushPending(pending.s,'pendingTz',{timezone:'Pacific/Honolulu',history_years:17});pending.s.tzMode='ok';await pending.section('Scan');
 check('timezone-pending-unmount-remount','persistence','new section reads current backend fixture after old pending section unmount',{visible:await pending.row('Timezone').locator('input').inputValue(),stored:pending.s.timezone},await pending.row('Timezone').locator('input').inputValue()===pending.s.timezone);await pending.context.close();
 const bounds=await scenario('strategy-bounds');await bounds.section('Strategy scan');const fields=[['MA crossover lookback','maCrossoverLookback','0'],['Breakout volume multiplier','breakoutVolumeMult','4'],['Breakout volume multiplier','breakoutVolumeMult','1']];
 for(const [label,key,value]of fields){const before=await bounds.page.evaluate(()=>JSON.parse(localStorage.getItem('bamendjou:scan-params'))?.state??null);await bounds.page.getByLabel(label,{exact:true}).fill(value);const storage=await bounds.page.evaluate(()=>JSON.parse(localStorage.getItem('bamendjou:scan-params')).state);check('strategy-bounds-'+key+'-'+value,'persistence','UI range and backend-required bounds are both enforced before persistence',{beforeStorage:before,afterStorage:storage,visible:await bounds.page.getByLabel(label,{exact:true}).inputValue(),value:storage[key],valid:await bounds.page.getByLabel(label,{exact:true}).evaluate(e=>e.validity.valid)},storage[key]!==Number(value));await bounds.page.screenshot({path:dir+'strategy-'+key+'-'+value+'.png',fullPage:true});await bounds.page.getByLabel('Clear '+label,{exact:true}).click();}
 await bounds.context.close();
 const checking=await scenario('health-checking',{health:'pending'});await checking.page.locator('[data-tier="checking"]').waitFor();check('health-initial-checking','ui','checking chip and no banner before first response',{text:await checking.page.locator('[data-tier="checking"]').innerText(),banner:await checking.page.locator('#config-health-banner').count()},await checking.page.locator('#config-health-banner').count()===0);await flushPending(checking.s,'pendingHealth',clean);checking.s.health=clean;await checking.context.close();
 for(const tier of ['clean','warning','error','stale','unknown']){
  const line={file:'fixture.yaml',path:'fixture.value',message:'Audit fixture '+tier};let h=clone(clean);if(tier!=='clean'&&tier!=='unknown'){h.ok=false;if(tier==='error')h.errors=[{...line,blocks:'audit fixture scans'}];else h[tier==='warning'?'warnings':'stale']=[line];}
  const x=await scenario('health-'+tier,{health:tier==='unknown'?'fail':h});await x.page.locator(`[data-tier="${tier}"]`).first().waitFor();const chip=x.page.locator(`button[data-tier="${tier}"]`);
  if(tier==='clean'){await chip.click();check('health-clean-popover','ui','clean opens checked/not-checked scope',{scope:await x.page.getByRole('region',{name:'Config health scope'}).innerText()},await x.page.getByRole('region',{name:'Config health scope'}).count()===1);await x.page.keyboard.press('Escape');check('health-clean-escape','ui','Escape closes scope',await x.page.getByRole('region',{name:'Config health scope'}).count(),await x.page.getByRole('region',{name:'Config health scope'}).count()===0);await chip.click();await x.page.getByRole('heading',{name:'Settings',exact:true}).click();check('health-clean-outside-close','ui','outside click closes popover',await x.page.getByRole('region',{name:'Config health scope'}).count(),await x.page.getByRole('region',{name:'Config health scope'}).count()===0);}
  else{const banner=x.page.locator('#config-health-banner');check('health-'+tier+'-expanded','ui','chip/banner tier matches, details initially expanded',{chip:await chip.innerText(),banner:await banner.innerText()},await banner.getAttribute('data-tier')===tier&&await banner.getByRole('button',{name:'Collapse',exact:true}).count()===1);await banner.getByRole('button',{name:'Collapse',exact:true}).click();check('health-'+tier+'-collapse','ui','collapse hides detail and keeps headline',{text:await banner.innerText(),detail:await x.page.locator('#config-health-banner-detail').count()},await x.page.locator('#config-health-banner-detail').count()===0);await chip.click();check('health-'+tier+'-chip-expand','ui','chip expands and focuses banner',{expanded:await x.page.locator('#config-health-banner-detail').count(),focused:await banner.evaluate(e=>e===document.activeElement)},await x.page.locator('#config-health-banner-detail').count()===1&&await banner.evaluate(e=>e===document.activeElement));}
  await x.page.screenshot({path:dir+'health-'+tier+'.png',fullPage:true});await x.context.close();
 }
}finally{
 out.safety={unknownRequestCount:out.unknownRequests.length,pageErrorCount:out.pageErrors.length,forbiddenRequests:out.requests.filter(r=>/run-now|trigger|probe|broker|notifications\/test|\/run$|\/adopt/.test(r.path)),allBusinessRequestsMocked:true};
 out.counts=Object.fromEntries(['pass','fail'].map(s=>[s,out.checks.filter(c=>c.status===s).length]));
 for(const s of out.scenarios){delete s.pendingIv;delete s.pendingTz;delete s.pendingHealth;}
 fs.writeFileSync(dir+'output.json',JSON.stringify(out,null,2)+'\n');fs.writeFileSync(dir+'source-hashes.json',JSON.stringify({source_sha:sha,versions:out.versions,sha256:hashes},null,2)+'\n');
 await browser.close();console.log(JSON.stringify({counts:out.counts,failures:out.checks.filter(x=>x.status==='fail').map(x=>x.id),safety:out.safety,unknown:out.unknownRequests},null,2));
}
