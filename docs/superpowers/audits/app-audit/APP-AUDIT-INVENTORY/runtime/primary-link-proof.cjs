/* Finish the two Primary actions omitted by the earlier prototype sequence. */
const fs=require('fs'),path=require('path'),crypto=require('crypto'),{createRequire}=require('module');
const root=path.resolve(__dirname,'../../../../../..'),req=createRequire(path.join(root,'frontend/package.json')),base='http://127.0.0.1:3017';
req('ts-node').register({transpileOnly:true,compilerOptions:{module:'CommonJS',moduleResolution:'node'}});
const {chromium}=req('@playwright/test'),inventory=require('../inventory.json');
const out=path.join(__dirname,'primary-link-evidence');fs.mkdirSync(out,{recursive:true});
const sha=s=>crypto.createHash('sha256').update(s).digest('hex'),network=[],payloads={},observations=[];let current='setup';
const write=(name,value)=>fs.writeFileSync(path.join(out,name),JSON.stringify(value,null,2)+'\n');
(async()=>{
 process.chdir(path.join(root,'frontend'));const {setupApiMocks}=req(path.join(root,'frontend/e2e/fixtures/api-mocks.ts'));
 const browser=await chromium.launch({headless:true,channel:'chrome'}),context=await browser.newContext({viewport:{width:1440,height:1000},serviceWorkers:'block',timezoneId:'Europe/Berlin'});
 await context.routeWebSocket(/.*/,ws=>{network.push({probe:current,method:'WEBSOCKET',path:new URL(ws.url()).pathname,action:'closed-before-connect'});ws.close();});
 await context.route('**/*',route=>{const r=route.request(),u=new URL(r.url());if(u.origin===base&&r.method()==='GET'&&!u.pathname.startsWith('/api/'))return route.continue();network.push({probe:current,method:r.method(),path:u.pathname,action:'blocked-unmatched'});return route.abort('blockedbyclient');});
 const page=await context.newPage();const realRoute=page.route.bind(page);
 page.route=(pattern,handler)=>realRoute(pattern,route=>{const r=route.request(),u=new URL(r.url());return handler(new Proxy(route,{get(target,key){if(key==='continue')return()=>{network.push({probe:current,method:r.method(),path:u.pathname,action:'blocked-fixture-continue'});return target.abort('blockedbyclient');};if(key==='fulfill')return opts=>{const body=String(opts.body??''),hash=sha(body);payloads[hash]={sha256:hash,body};network.push({probe:current,method:r.method(),path:u.pathname,action:'mocked',status:opts.status??200,response_sha256:hash,request_body_sha256:null});return target.fulfill(opts);};return typeof target[key]==='function'?target[key].bind(target):target[key];}}));});
 await setupApiMocks(page);await page.goto(base+'/dashboard',{waitUntil:'domcontentloaded',timeout:90000});await page.getByRole('heading',{name:'Dashboard',exact:true}).waitFor();
 for(const [href,expected,heading]of[['/screener','/screener/step-1-regime','Market Regime'],['/strategy-watch','/strategy-watch','Strategy Watch']]){
  if(!await page.locator('nav[aria-label="Primary"]').count()){await page.goto(base+'/dashboard');await page.getByRole('heading',{name:'Dashboard',exact:true}).waitFor();}
  current='primary-link:'+href;const before=await page.evaluate(()=>({local:Object.fromEntries(Object.entries(localStorage)),session:Object.fromEntries(Object.entries(sessionStorage))}));
  await page.locator('nav[aria-label="Primary"] a[href="'+href+'"]').click();await page.waitForURL('**'+expected,{timeout:90000});await page.getByRole('heading',{name:heading,exact:true}).waitFor();
  observations.push({id:current,status:'observed',route_id:inventory.route_entries.find(r=>r.route===expected&&r.classification==='url-page').id,surface_ids:[inventory.definitions.find(d=>d.component==='NavItems').id],fixture_identity:'primary-link:'+href,assertion:'actual Primary anchor click reaches final URL and visible expected heading',storage_before:before,storage:await page.evaluate(()=>({local:Object.fromEntries(Object.entries(localStorage)),session:Object.fromEntries(Object.entries(sessionStorage))})),state:await page.evaluate(()=>({url:location.pathname,title:document.title,text:document.body.innerText,headings:Array.from(document.querySelectorAll('h1,h2')).map(n=>n.textContent),rails:Array.from(document.querySelectorAll('aside')).map(n=>({text:n.innerText}))})),network_indices:network.map((n,i)=>n.probe===current?i:-1).filter(i=>i>=0)});
  console.log(current+': visible '+heading);
  if(href==='/screener'){await page.goto(base+'/dashboard');await page.getByRole('heading',{name:'Dashboard',exact:true}).waitFor();}
 }
 write('observations.json',observations);write('network.json',network);write('mock-payloads.json',payloads);write('page-errors.json',[]);write('provenance.json',{source_baseline:inventory.source_baseline,real_backend_requests_allowed:0,backend_mode:'browser fixtures; unmatched egress denied',browser:browser.version(),playwright:req('@playwright/test/package.json').version,next:req('next/package.json').version,node:process.version,date:new Date().toISOString(),harness_start_sha256:{'primary-link-proof.cjs':sha(fs.readFileSync(__filename))},observation_count:observations.length,failure_count:0});await browser.close();
})().catch(error=>{write('fatal.json',{error:String(error.message)});process.exitCode=1;});
