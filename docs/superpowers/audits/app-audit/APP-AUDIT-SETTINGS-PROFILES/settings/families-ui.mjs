// Isolated Chromium; ALL API mocked; no sends, triggers, probes, orders, or jobs.
import {chromium} from '../../../../../../frontend/node_modules/playwright/index.mjs';
import fs from 'node:fs';
const dir = new URL('.', import.meta.url).pathname;
const out = {source_sha:'880c8441841cc22d5090cdc5f984e4cf7e3d9a8d',boundary:'ALL API MOCKED',requests:[],checks:[],pageErrors:[],unknownRequests:[]};
const browser = await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox','--no-proxy-server']});
out.browser=browser.version();
const context=await browser.newContext({viewport:{width:1440,height:1100}}),page=await context.newPage();
page.on('pageerror', e=>out.pageErrors.push(e.message));
const notifications={gmail:{enabled:false,to:'',smtp_user:''},telegram:{enabled:false,chat_id:''}};
const schedules={
 '/api/data/ingest/schedule':{enabled:false,time:'02:00',next_run:null},
 '/api/data/edgar/schedule':{enabled:false,time:'03:00',next_run:null},
 '/api/data/sp500/schedule':{enabled:false,time:'04:00',next_run:null},
 '/api/strategy-tuning/schedule':{enabled:false,time:'05:00',days_of_week:[5],next_run:null},
};
let failPath=null;
const clone=v=>JSON.parse(JSON.stringify(v));
const reply=(route,data,status=200)=>route.fulfill({status,contentType:'application/json',headers:{'Access-Control-Allow-Origin':'*','Access-Control-Allow-Headers':'*','Access-Control-Allow-Methods':'*'},body:JSON.stringify(data)});
await context.route('**/*',async route=>{
 const request=route.request(),url=new URL(request.url()),path=url.pathname,method=request.method();
 if(url.hostname==='127.0.0.1'&&url.port==='3027'&&!path.startsWith('/api/'))return route.continue();
 let body=null;try{body=request.postDataJSON()}catch{}
 const record={path,method,body};out.requests.push(record);
 if(method==='OPTIONS')return reply(route,{});
 if(path==='/settings/notifications'){
  if(method==='POST'){
   if(failPath===path){record.response={detail:'injected mock failure'};record.status=500;return reply(route,record.response,500);}
   notifications.gmail={enabled:body.gmail.enabled,to:body.gmail.to,smtp_user:body.gmail.smtp_user};
   notifications.telegram={enabled:body.telegram.enabled,chat_id:body.telegram.chat_id};
  }
  record.response=clone(notifications);record.status=200;return reply(route,notifications);
 }
 if(Object.hasOwn(schedules,path)){
  if(method==='POST'){
   if(failPath===path){record.response={detail:'injected mock failure'};record.status=500;return reply(route,record.response,500);}
   schedules[path]={...body,next_run:null};
  }
  record.response=clone(schedules[path]);record.status=200;return reply(route,schedules[path]);
 }
 if(path==='/api/config/health')return reply(route,{ok:true,pid:1234,checked:['isolated fixture schema'],not_checked:['live configuration'],errors:[],warnings:[],stale:[]});
 if(path==='/settings/history-retention')return reply(route,{historyRetentionYears:10});
 if(path==='/api/strategy-tuning/jobs')return reply(route,{count:0,completed:0,failed:0,running:0});
 if(path==='/api/config/iv-thresholds')return reply(route,Object.fromEntries(['Intraday','Swing','Position'].map(h=>[h,{abs_pass_max:34,abs_caution_max:55,rank_pass_max:34,rank_caution_max:55}])));
 if(['/api/watchlist','/api/portfolio','/api/data-sources','/api/scan-schedule'].includes(path))return reply(route,[]);
 if(path==='/settings/scheduling')return reply(route,{timezone:'Europe/Berlin',history_years:17});
 if(path==='/settings/scheduled-scan-retention')return reply(route,{scheduledScanRunRetentionDays:90});
 if(path.endsWith('/last')||path.endsWith('/last-request'))return reply(route,null);
 if(path.endsWith('/last-run'))return reply(route,{status:null,updated_at:null});
 out.unknownRequests.push({path,method});return reply(route,{detail:'Denied by isolated audit harness'},404);
});
const section=label=>page.locator('aside button').filter({has:page.getByText(label,{exact:true})}).click();
const row=label=>page.locator('[class*="row"]').filter({has:page.getByText(label,{exact:true})}).filter({has:page.locator('input,button')}).last();
const check=(id,expected,observed,ok)=>out.checks.push({id,expected,observed:clone(observed),status:ok?'pass':'fail'});
await page.goto('http://127.0.0.1:3027/settings');await page.getByRole('heading',{name:'Settings',exact:true}).waitFor();
await section('Notifications');await page.getByPlaceholder('you@gmail.com').first().waitFor();await page.waitForTimeout(150);
const before=clone(notifications);
await row('Enable Gmail alerts').getByRole('switch').click();
await row('Enable Telegram alerts').getByRole('switch').click();
await row('To address').locator('input').fill('sink@audit.invalid');
await row('SMTP User').locator('input').fill('fixture@audit.invalid');
await row('Password').locator('input').fill('FAKE-AUDIT-PASSWORD');
await row('Bot token').locator('input').fill('FAKE-AUDIT-TOKEN');
await row('Chat ID').locator('input').fill('FAKE-AUDIT-CHAT');
let start=out.requests.length;
await page.getByRole('button',{name:'Save settings',exact:true}).click();await page.getByText('Settings saved',{exact:true}).waitFor();
check('notifications-ui-save','UI fields become POST and readback; write-only inputs cleared; no sends',
 {before,after:notifications,requests:out.requests.slice(start),password:await row('Password').locator('input').inputValue(),token:await row('Bot token').locator('input').inputValue()},
 notifications.gmail.to==='sink@audit.invalid'&&notifications.telegram.enabled===true&&await row('Password').locator('input').inputValue()===''&&await row('Bot token').locator('input').inputValue()==='');
failPath='/settings/notifications';await row('To address').locator('input').fill('changed@audit.invalid');start=out.requests.length;
await page.getByRole('button',{name:'Save settings',exact:true}).click();await page.getByText('Save failed: 500',{exact:true}).waitFor();
check('notifications-ui-failed-save','500 shown and stored mock config unchanged',
 {visible:await row('To address').locator('input').inputValue(),server:notifications,requests:out.requests.slice(start)},notifications.gmail.to==='sink@audit.invalid');
failPath=null;await section('Appearance');await section('Notifications');await page.waitForTimeout(150);
check('notifications-ui-remount-readback','remount rehydrates last successful config with blank secrets',
 {to:await row('To address').locator('input').inputValue(),enabled:await row('Enable Gmail alerts').getByRole('switch').getAttribute('aria-checked')},
 await row('To address').locator('input').inputValue()==='sink@audit.invalid'&&await row('Enable Gmail alerts').getByRole('switch').getAttribute('aria-checked')==='true');
await page.screenshot({path:dir+'notifications-family.png',fullPage:true});
for(const [index,name,path,time] of [[0,'ingestion','/api/data/ingest/schedule','01:17'],[1,'edgar','/api/data/edgar/schedule','04:23'],[2,'sp500','/api/data/sp500/schedule','16:41'],[0,'tuning','/api/strategy-tuning/schedule','05:37']]){
 await section(name==='tuning'?'Strategy Tuning':'Data');await page.waitForTimeout(100);
 const input=page.locator('input[type=time]').nth(index),toggle=page.getByRole('switch').nth(index),save=page.getByRole('button',{name:'Save schedule',exact:true}).nth(index);
 const before={server:clone(schedules[path]),visibleTime:await input.inputValue(),disabled:await input.isDisabled(),enabled:await toggle.getAttribute('aria-checked')};
 if(await toggle.getAttribute('aria-checked')==='false')await toggle.click();
 await input.fill(time);
 if(name==='tuning'){await page.getByLabel('Mon',{exact:true}).check();await page.getByLabel('Wed',{exact:true}).check();}
 start=out.requests.length;await save.click();await page.waitForTimeout(100);
 const after={server:clone(schedules[path]),visibleTime:await input.inputValue(),requests:out.requests.slice(start)};
 check(name+'-schedule-ui-save','enabled/time and tuning weekdays flow to save payload', {before,after},schedules[path].time===time&&schedules[path].enabled===true&&(name!=='tuning'||JSON.stringify(schedules[path].days_of_week)==='[0,2,5]'));
 failPath=path;await input.fill('22:59');start=out.requests.length;await save.click();await page.getByText('Save failed',{exact:true}).waitFor();
 check(name+'-schedule-ui-failed-save','failed save visible and mock backend retains prior successful time',
  {visibleTime:await input.inputValue(),server:schedules[path],requests:out.requests.slice(start)},schedules[path].time===time);
 failPath=null;await section('Appearance');await section(name==='tuning'?'Strategy Tuning':'Data');await page.waitForTimeout(100);
 check(name+'-schedule-ui-remount-readback','remount rehydrates saved schedule',
  {visibleTime:await input.inputValue(),enabled:await toggle.getAttribute('aria-checked')},await input.inputValue()===time&&await toggle.getAttribute('aria-checked')==='true');
}
await page.screenshot({path:dir+'tuning-family.png',fullPage:true});
check('families-ui-no-side-effects','no send/probe/trigger/job/adopt endpoint called',out.requests.filter(r=>r.method!=='GET'&&r.method!=='OPTIONS'),
 out.requests.filter(r=>r.method==='POST').every(r=>r.path==='/settings/notifications'||Object.hasOwn(schedules,r.path)));
const redact=(key,value)=>(['smtp_password','bot_token'].includes(key)&&value)?'[redacted fake secret]':value;
fs.writeFileSync(dir+'families-ui-output.json',JSON.stringify(out,redact,2)+'\n');await browser.close();
console.log(JSON.stringify({checks:out.checks.map(({id,status})=>({id,status})),unknownRequests:out.unknownRequests,pageErrors:out.pageErrors},null,2));
