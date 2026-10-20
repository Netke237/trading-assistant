// Evidence only: isolated Chromium, synthetic storage, all API/WebSockets mocked.
const fs = require('fs'), path = require('path'), os = require('os'), crypto = require('crypto'), cp = require('child_process');
const root = path.resolve(__dirname, '../../../../../../..');
const { chromium } = require(path.join(root, 'frontend/node_modules/playwright'));
const origin = process.env.AUDIT_ORIGIN || 'http://127.0.0.1:3027';
const KEY = 'bamendjou:search-profiles', SETTINGS = 'bamendjou-settings', THEME = 'bamendjou:theme';
const pack = JSON.parse(fs.readFileSync(path.join(root, 'docs/search-profiles/search-profiles-export.json'), 'utf8'));
const importer = fs.readFileSync(path.join(root, 'docs/search-profiles/import-search-profiles.js'), 'utf8');
const fixture = { version: 5, state: { profiles: [{ ...pack.state.profiles[0], id: 'storage-audit-profile', name: 'Storage baseline' }] } };
const out = { source_sha: cp.execFileSync('git', ['rev-parse','HEAD'], { cwd: root, encoding:'utf8' }).trim(), original_source_sha:'880c8441841cc22d5090cdc5f984e4cf7e3d9a8d', origin, mocked:true, injection:'Storage.prototype.setItem throws DOMException only for selected exact audit-owned key or selected backup prefix; getItem remains native; no disk quota filling', checks:[], cases:[], api_requests:[], blocked:[], errors:[] };
function check(id, expected, actual) { out.checks.push({id,status:JSON.stringify(expected)===JSON.stringify(actual)?'pass':'fail',expected,actual}); }
function clean(s) { return String(s).replaceAll(root,'<repo>').replace(/\/tmp\/storage-audit-[^/ ]+/g,'<temporary-browser-profile>'); }
async function mock(ctx) {
  await ctx.routeWebSocket('**/*', ws=>ws.close());
  await ctx.route('**/*', async r=>{
    const req=r.request(), u=new URL(req.url());
    if (u.pathname.startsWith('/api/')) {
      out.api_requests.push({method:req.method(),path:u.pathname,mocked:true});
      let body=[];
      if(u.pathname.includes('thresholds'))body={};
      else if(u.pathname.endsWith('/regime'))body={overall:'CAUTION',omm:{state:'Choppy'}};
      else if(u.pathname.endsWith('/status'))body={status:'idle'};
      if(u.pathname.includes('/last'))return r.fulfill({status:404,headers:{'access-control-allow-origin':'*'},body:'{}'});
      return r.fulfill({status:200,headers:{'access-control-allow-origin':'*'},contentType:'application/json',body:JSON.stringify(body)});
    }
    if(u.origin!==origin){out.blocked.push(u.origin);return r.abort();}
    return r.continue();
  });
  ctx.on('page',p=>p.on('pageerror',e=>out.errors.push(clean(e.message))));
}
async function open(ctx, route='profiles') {
  const p=await ctx.newPage();p.setDefaultTimeout(15000);
  await p.goto(origin+(route==='profiles'?'/screener/step-3-direction':'/settings'),{waitUntil:'domcontentloaded'});
  if(route==='profiles')await p.getByLabel('Search profile',{exact:true}).waitFor();
  else await p.getByRole('heading',{name:'Settings',exact:true}).waitFor();
  await hydrated(p);
  return p;
}
async function hydrated(p){await p.waitForFunction(()=>{const e=document.querySelector('select[aria-label="Search profile"]')||document.querySelector('footer button');return e&&Object.keys(e).some(k=>k.startsWith('__reactProps$')&&(typeof e[k].onClick==='function'||typeof e[k].onChange==='function'));});}
async function read(p) {return p.evaluate(keys=>({...Object.fromEntries(keys.map(k=>[k,localStorage.getItem(k)])),backups:Object.fromEntries(Object.keys(localStorage).filter(k=>k.startsWith(keys[0]+':backup-')).map(k=>[k,localStorage.getItem(k)]))}),[KEY,SETTINGS,THEME]);}
async function profileUI(p){return {options:await p.getByLabel('Search profile',{exact:true}).locator('option').allTextContents(),dialog:await p.getByRole('dialog').allTextContents(),body:(await p.locator('body').innerText()).slice(-1200)};}
function row(p,label){return p.getByText(label,{exact:true}).locator('xpath=../..').locator('input').first();}
async function settingsTab(p,name){await p.getByRole('button',{name:new RegExp('^'+name)}).first().click();}
async function inject(p,key,name,prefix=false){await p.evaluate(({key,name,prefix})=>{
  const native=Storage.prototype.setItem;window.__auditNativeSetItem=native;window.__auditFault={key,name,prefix,attempts:[]};
  Storage.prototype.setItem=function(k,v){if(this===localStorage&&(prefix?k.startsWith(key):k===key)){window.__auditFault.attempts.push({key:k,value:String(v),name});throw new DOMException('Audit injected '+name,name);}return native.call(this,k,v);};
},{key,name,prefix});}
async function uninject(p){return p.evaluate(()=>{const f=window.__auditFault;Storage.prototype.setItem=window.__auditNativeSetItem;return f;});}
async function seedProfile(ctx){await ctx.addInitScript(({k,v})=>{if(!sessionStorage.getItem('audit-seeded')){localStorage.setItem(k,JSON.stringify(v));sessionStorage.setItem('audit-seeded','yes');}},{k:KEY,v:fixture});}
async function profileFailure(browser,operation,name){
  const ctx=await browser.newContext({viewport:{width:1600,height:1000}});await mock(ctx);await seedProfile(ctx);const p=await open(ctx);
  await p.getByLabel('Search profile',{exact:true}).selectOption('storage-audit-profile');
  const before=await read(p);const uiBefore=await profileUI(p);let evalError=null;const errorsStart=out.errors.length;
  if(operation==='update')await p.getByRole('button',{name:'Bearish',exact:true}).click();
  const prefix=operation==='import-backup';await inject(p,prefix?KEY+':backup-':KEY,name,prefix);
  if(operation==='save'){await p.getByRole('button',{name:'Save as new…',exact:true}).click();await p.getByPlaceholder('Profile name').fill('Storage failed save');await p.getByRole('button',{name:'Save',exact:true}).click();}
  else if(operation==='update')await p.getByRole('button',{name:'Update “Storage baseline”',exact:true}).click();
  else if(operation==='rename'){await p.getByRole('button',{name:'Rename',exact:true}).click();await p.getByRole('dialog').locator('input').fill('Storage failed rename');await p.getByRole('dialog').getByRole('button',{name:'Save',exact:true}).click();}
  else if(operation==='delete'){await p.getByRole('button',{name:'Delete',exact:true}).click();await p.getByRole('dialog').getByRole('button',{name:'Confirm',exact:true}).click();}
  else try{await p.evaluate(code=>eval(code),importer);}catch(e){evalError=clean(e.message);}
  await p.waitForTimeout(100);const after=await read(p),uiAfter=await profileUI(p);const fault=await uninject(p);
  let uiReadbackBeforeReload=null;
  if(operation==='update'){
    await p.getByLabel('Search profile',{exact:true}).selectOption('');await p.getByRole('button',{name:'Bullish',exact:true}).click();await p.getByLabel('Search profile',{exact:true}).selectOption('storage-audit-profile');
    uiReadbackBeforeReload=await p.getByRole('button',{name:'Bearish',exact:true}).getAttribute('aria-pressed');
    // The persisted scan context exposes what applying the in-memory profile actually read.
    uiReadbackBeforeReload={context:await p.evaluate(()=>JSON.parse(localStorage.getItem('bamendjou-scan-store')).state.context)};
  }
  await p.reload({waitUntil:'domcontentloaded'});await p.getByLabel('Search profile',{exact:true}).waitFor();await hydrated(p);const reloaded=await read(p),uiReloaded=await profileUI(p);
  const c={id:'profile-'+operation+'-'+name,before,after,reloaded,uiBefore,uiAfter,uiReloaded,uiReadbackBeforeReload,fault,evalError,pageErrors:out.errors.slice(errorsStart)};out.cases.push(c);
  check(c.id+' throws injected error',true,fault.attempts.length>0);
  check(c.id+' prior raw bytes retained',before[KEY],after[KEY]);
  check(c.id+' disk reload retained',before[KEY],reloaded[KEY]);
  if(operation==='save'||operation==='rename'||operation==='delete')check(c.id+' memory profile list rolled back',uiBefore.options,uiAfter.options);
  else if(operation==='update')check(c.id+' memory update rolled back','Bullish',uiReadbackBeforeReload.context.direction);
  else {check(c.id+' import exposes storage error',true,!!evalError);check(c.id+' backup state',operation==='import-primary'?true:0,operation==='import-primary'?Object.values(after.backups).includes(before[KEY]):Object.keys(after.backups).length);}
  await ctx.close();
}
async function settingsSnapshot(p,kind){
  if(kind==='theme')return {theme:await p.locator('html').getAttribute('data-theme')};
  if(kind==='markov')return {lookback:await row(p,'Lookback (bars)').inputValue()};
  return {caution:await row(p,'Caution below (%)').inputValue()};
}
async function settingsFailure(browser,kind,name){
  const ctx=await browser.newContext({viewport:{width:1600,height:1000}});await mock(ctx);const p=await open(ctx,'settings');
  await settingsTab(p,kind==='theme'?'Appearance':kind==='markov'?'Regime':'Scan');
  // Establish non-null prior bytes through supported UI before injecting faults.
  if(kind==='theme'){await p.getByRole('button',{name:'Switch to light mode'}).first().click();}
  else if(kind==='markov'){await row(p,'Lookback (bars)').fill('30');}
  else {await row(p,'Caution below (%)').fill('61');await row(p,'Caution below (%)').blur();}
  const before=await read(p),uiBefore=await settingsSnapshot(p,kind),errorsStart=out.errors.length;await inject(p,kind==='theme'?THEME:SETTINGS,name);
  if(kind==='theme')await p.getByRole('button',{name:'Switch to dark mode'}).first().click();
  else if(kind==='markov')await row(p,'Lookback (bars)').fill('45');
  else{await row(p,'Caution below (%)').fill('72');await row(p,'Caution below (%)').blur();}
  await p.waitForTimeout(100);const uiAfter=await settingsSnapshot(p,kind),after=await read(p);
  await p.getByRole('button',{name:'Save changes',exact:true}).click();const savedConfirmation=await p.getByRole('button',{name:'Saved',exact:true}).isVisible();const fault=await uninject(p);
  await p.reload({waitUntil:'domcontentloaded'});await p.getByRole('heading',{name:'Settings',exact:true}).waitFor();await hydrated(p);await settingsTab(p,kind==='theme'?'Appearance':kind==='markov'?'Regime':'Scan');
  const reloaded=await read(p),uiReloaded=await settingsSnapshot(p,kind),id='settings-'+kind+'-'+name;
  out.cases.push({id,before,after,reloaded,uiBefore,uiAfter,uiReloaded,savedConfirmation,fault,pageErrors:out.errors.slice(errorsStart)});
  check(id+' injection reached',true,fault.attempts.length>0);check(id+' prior raw retained',before[kind==='theme'?THEME:SETTINGS],after[kind==='theme'?THEME:SETTINGS]);
  check(id+' UI rollback',uiBefore,uiAfter);check(id+' no false Saved',false,savedConfirmation);check(id+' reload old value',uiBefore,uiReloaded);
  await ctx.close();
}
async function futureVersion(browser){const ctx=await browser.newContext({viewport:{width:1600,height:1000}});await mock(ctx);
  const future={...fixture,version:9999,state:{...fixture.state,futureAuditSentinel:'must-survive-older-client'}};
  await ctx.addInitScript(({k,v})=>{if(!sessionStorage.getItem('audit-seeded')){localStorage.setItem(k,JSON.stringify(v));sessionStorage.setItem('audit-seeded','yes');}},{k:KEY,v:future});
  const p=await open(ctx);const after=await read(p);out.cases.push({id:'unknown-future-version',beforeRaw:JSON.stringify(future),after,ui:await profileUI(p)});
  check('unknown future version preserves bytes until explicit compatible migration',JSON.stringify(future),after[KEY]);await ctx.close();
}
async function restartAndTabs(){
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'storage-audit-'));let ctx;
  try{ctx=await chromium.launchPersistentContext(dir,{executablePath:'/usr/bin/chromium',headless:true,viewport:{width:1600,height:1000},args:['--no-sandbox']});await mock(ctx);
    let p=await open(ctx,'settings');await settingsTab(p,'Appearance');await p.getByRole('button',{name:'Switch to light mode'}).first().click();await settingsTab(p,'Regime');await row(p,'Lookback (bars)').fill('35');await settingsTab(p,'Scan');await row(p,'Caution below (%)').fill('63');await row(p,'Caution below (%)').blur();
    const before=await read(p);await ctx.close();ctx=await chromium.launchPersistentContext(dir,{executablePath:'/usr/bin/chromium',headless:true,viewport:{width:1600,height:1000},args:['--no-sandbox']});await mock(ctx);p=await open(ctx,'settings');const after=await read(p);
    await settingsTab(p,'Regime');const markov=await settingsSnapshot(p,'markov');await settingsTab(p,'Scan');const confidence=await settingsSnapshot(p,'confidence');const theme=await p.locator('html').getAttribute('data-theme');
    check('process restart exact Settings raw',before[SETTINGS],after[SETTINGS]);check('process restart exact theme raw',before[THEME],after[THEME]);check('process restart UI values',{theme:'light',lookback:'35',caution:'63'},{theme,lookback:markov.lookback,caution:confidence.caution});
    const stale=await open(ctx,'settings');await settingsTab(stale,'Regime');const staleBefore=await settingsSnapshot(stale,'markov');
    const events=[];await stale.exposeFunction('auditStorageEvent',e=>events.push(e));await stale.evaluate(()=>window.addEventListener('storage',e=>window.auditStorageEvent({key:e.key,newValue:e.newValue})));
    await settingsTab(p,'Appearance');await p.getByRole('button',{name:'Switch to dark mode'}).first().click();await settingsTab(p,'Regime');await row(p,'Lookback (bars)').fill('55');await p.waitForTimeout(200);
    const staleAfter={...await settingsSnapshot(stale,'markov'),theme:await stale.locator('html').getAttribute('data-theme')},rawAfterOtherTab=await read(stale);
    check('theme advertises sync across tabs','dark',staleAfter.theme);
    // Settings has no advertised cross-tab synchronization; measure stale overwrite separately.
    await settingsTab(stale,'Scan');await row(stale,'Caution below (%)').fill('64');await row(stale,'Caution below (%)').blur();const afterStaleWrite=await read(p);
    check('stale Settings writer preserves unrelated latest Markov',55,JSON.parse(afterStaleWrite[SETTINGS]).state.markov.lookback);
    out.cases.push({id:'process-restart-and-cross-tab',before,after,restartUI:{theme,markov,confidence},staleBefore,staleAfter,rawAfterOtherTab,afterStaleWrite,storageEvents:events});
  }finally{if(ctx)await ctx.close();fs.rmSync(dir,{recursive:true,force:true});}
}
(async()=>{const browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox']});out.versions={browser:browser.version(),node:process.version,playwright:require(path.join(root,'frontend/node_modules/playwright/package.json')).version,next:require(path.join(root,'frontend/node_modules/next/package.json')).version};
try{for(const name of ['QuotaExceededError','SecurityError']){for(const operation of ['save','update','rename','delete','import-backup','import-primary']){console.log(operation,name);await profileFailure(browser,operation,name);}for(const kind of ['theme','markov','confidence']){console.log(kind,name);await settingsFailure(browser,kind,name);}}await futureVersion(browser);}finally{await browser.close();}await restartAndTabs();
})().catch(e=>{out.fatal=clean(e.stack||e.message);process.exitCode=1;}).finally(()=>{
  out.totals={pass:out.checks.filter(x=>x.status==='pass').length,fail:out.checks.filter(x=>x.status==='fail').length};
  fs.writeFileSync(path.join(__dirname,'output.json'),JSON.stringify(out,null,2)+'\n');console.log(JSON.stringify({totals:out.totals,fatal:out.fatal}));
});
