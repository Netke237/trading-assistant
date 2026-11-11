// Offline design acceptance only. Requires the repository's existing Playwright.
// No application server, save, notification, scan or brokerage endpoint is used.
const fs = require('fs');
const path = require('path');
const args = require('util').parseArgs({options:{'repo-root':{type:'string'},output:{type:'string'},browser:{type:'string',default:'/usr/bin/chromium'},'base-url':{type:'string',default:'http://127.0.0.1:3196/'}}}).values;
const baseURL = new URL(args['base-url']);
if(!['127.0.0.1','localhost','[::1]'].includes(baseURL.hostname)||baseURL.port==='3001')throw new Error('Only an isolated loopback static preview server is allowed');
const root = path.resolve(args['repo-root'] || path.resolve(__dirname,'../../../..'));
const out = path.resolve(args.output || path.join(__dirname,'evidence'));
fs.mkdirSync(out,{recursive:true});
const {chromium} = require(require.resolve('playwright',{paths:[path.join(root,'frontend'),'/workspace/trading-assistant/frontend']}));
const report={checks:[],pageErrors:[],networkRequests:[],staticDocumentRequests:[],screenshots:[]};
function check(value,message){report.checks.push({message,passed:!!value});if(!value)throw new Error(message)}
async function snap(page,name){await page.locator('#toast').evaluate(e=>e.hidden=true);const file=path.join(out,name+'.png');await page.screenshot({path:file,fullPage:true});report.screenshots.push(path.basename(file))}
async function layout(page,label){check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),label+': no page horizontal overflow')}
async function pageFor(browser,file,width,theme){
 const context=await browser.newContext({viewport:{width,height:1000}});const page=await context.newPage();
 page.on('pageerror',e=>report.pageErrors.push(e.message));
 const permitted=req=>req.method()==='GET'&&new URL(req.url()).origin===baseURL.origin&&/\/(?:stocks-preview|prebreakout-preview|index)\.html$/.test(new URL(req.url()).pathname);
 page.on('request',req=>{if(/^https?:/.test(req.url()))(permitted(req)?report.staticDocumentRequests:report.networkRequests).push(req.url())});
 await context.route(/^https?:/,route=>permitted(route.request())?route.continue():route.abort());
 await page.goto(new URL(file,baseURL).href);
 if(theme==='light')await page.locator('#theme').click();
 return {page,context};
}
async function stocks(browser,width,theme){
 const {page,context}=await pageFor(browser,'stocks-preview.html',width,theme);const tag=`stocks-${width}-${theme}`;
 check(await page.locator('#methods [data-method]').count()===1,tag+': one method initially');
 check(await page.locator('#methods [data-method=ladder]').count()===1,tag+': available edited Ladder on initial view');
 check(await page.locator('details[open]').count()===0,tag+': details initially closed');
 check(await page.locator('#selected-review').innerText().then(t=>t.includes('Choose a method')),tag+': no decision selected by viewing');
 check(await page.locator('#stock-qualification').evaluate(e=>e.nextElementSibling.id)==='backtest-evidence',tag+': qualification and backtest adjacent');
 await layout(page,tag+' initial');
 if(width===1366)await snap(page,tag+'-initial');
 await page.locator('#compare').click();
 check(await page.locator('#methods [data-method]').count()===2,tag+': compare has two methods');
 check(await page.locator('#methods').innerText().then(t=>t.includes('Results appear after you run')),tag+': comparing does not compute');
 await page.getByRole('button',{name:'Estimate Monte Carlo',exact:true}).click();
 await page.getByRole('button',{name:'Compute Arithmetic Plan',exact:true}).click();
 check(await page.locator('[data-method=arith] .warning').first().innerText().then(t=>t.includes('$196.00')&&t.includes('$194.00')),tag+': differing calculation and execution stops explicit');
 check(await page.locator('#selected-review').innerText().then(t=>t.includes('Choose a method')),tag+': running methods does not select decision');
 let dims=await page.locator('#methods [data-method]').evaluateAll(es=>es.map(e=>({height:e.getBoundingClientRect().height,width:e.getBoundingClientRect().width,table:e.querySelector('.targets table')?.getBoundingClientRect().top})));
 check(Math.abs(dims[0].height-dims[1].height)<2,tag+': compared cards have equal height');
 check(Math.abs(dims[0].width-dims[1].width)<2,tag+': compared cards have equal width');
 check(Math.abs(dims[0].table-dims[1].table)<2,tag+': common target table headers align despite the Arithmetic stop warning');
 await layout(page,tag+' comparison');
 if(width===1366)await snap(page,tag+'-compare');
 await page.locator('#pick-methods').getByRole('button',{name:'Arithmetic',exact:true}).click();
 await page.locator('#pick-targets').getByRole('button',{name:'2R · $208.00',exact:true}).click();
 check(await page.locator('#selected-review').innerText().then(t=>t.includes('$80.00')&&t.includes('$196.00')&&t.includes('$194.00')),tag+': selected Arithmetic outcome and both stops');
 const before=await page.locator('#selected-review').innerText();
 await page.locator('[data-view=ladder]').click();
 check(await page.locator('#methods [data-method]').count()===3,tag+': all three methods supported');
 check(await page.locator('#selected-review').innerText()===before,tag+': method-view changes preserve selected decision');
 dims=await page.locator('#methods [data-method]').evaluateAll(es=>es.map(e=>e.getBoundingClientRect().width));
 check(Math.max(...dims)-Math.min(...dims)<2,tag+': third card keeps the same width');
 await page.locator('#shares').fill('25');
 check(await page.locator('#selected-review').innerText().then(t=>t.includes('$200.00')&&t.includes('25 shares')),tag+': quantity changes selected outcome');
 check(await page.locator('#exit-plan .risk-position').innerText()==='$150.00',tag+': current execution risk uses194stop');
 check(await page.locator('#position-value').innerText()==='$5,000.00',tag+': position value uses entered shares');
 await page.locator('#pick-methods').getByRole('button',{name:'Ladder',exact:true}).click();
 await page.locator('#pick-targets').getByRole('button',{name:'T1 · $212.00',exact:true}).click();
 check(await page.locator('#selected-review').innerText().then(t=>t.includes('$300.00')&&t.includes('Not supplied')),tag+': Ladder has correct outcome and no borrowed statistics');
 await page.locator('#pin').click();await page.locator('#basket').click();
 check(await page.locator('#dialog').isVisible(),tag+': basket sample review opens');
 check(await page.locator('#dialog-body').innerText().then(t=>t.includes('$5,000.00')&&t.includes('Blocked')),tag+': basket entered quantity and execution block');
 await page.getByRole('button',{name:'Close preview dialog',exact:true}).click();
 await page.locator('[data-method=arith] details[data-detail=arith-race] > summary').click();
 check(await page.locator('[data-detail=arith-race]').innerText().then(t=>t.includes('55%')&&t.includes('35%')&&t.includes('10%')),tag+': graphical race remains under Arithmetic');
 await page.locator('#stop-explanation > summary').click();await page.locator('#check-structure').click();
 check(await page.locator('#structure-result').isVisible(),tag+': existing structural reference reachable');
 check(await page.locator('[aria-label="Execution stock stop"]').inputValue()==='194.00',tag+': structure lookup never overwrites execution stop');
 await page.locator('#stock-qualification > summary').click();await page.locator('#backtest-evidence > summary').click();
 check(await page.locator('#backtest-evidence').innerText().then(t=>t.includes('Sharpe')&&t.includes('Expectancy')&&t.includes('100')),tag+': full backtest evidence reachable');
 if(width===1366)await snap(page,tag+'-expanded');
 check(await page.getByRole('button',{name:'Market order · blocked',exact:true}).isDisabled(),tag+': broker execution remains blocked');
 await context.close();
}
async function scanner(browser,width,theme){
 const {page,context}=await pageFor(browser,'prebreakout-preview.html',width,theme);const tag=`scanner-${width}-${theme}`;
 check(await page.locator('details[open]').count()===0,tag+': supporting detail initially closed');
 if(width===1366)await snap(page,tag+'-initial');
 for(const mode of ['pre','ema','fib']){
  await page.locator(`[data-mode=${mode}]`).click();
  check(await page.locator('.candidate-row').count()===3,tag+': '+mode+' candidates retained');
  await page.locator('[aria-label="Select MSFT"]').press('Enter');
  check(await page.locator('#selected-panel .panelhead').innerText().then(t=>t.includes('MSFT')&&!t.includes('AAPL')),tag+': '+mode+' keyboard selection owns chart');
  await page.locator('[aria-label="Select AAPL"]').click();
  if(width===1366)await snap(page,tag+'-'+mode+'-collapsed');
  await page.locator('#setup-evidence > summary').click();
  const text=await page.locator('#setup-evidence').innerText();
  check(mode==='pre'?text.includes('Range is a qualification gate')&&text.includes('volume below 0.90'):mode==='fib'?text.includes('proximity only')&&text.includes('1.5%'):text.includes('historical signal confidence'),tag+': '+mode+' distinct metric meanings');
  check(await page.locator('#scan-context').innerText().then(t=>t.includes(mode==='ema'?'Original Pullback':'Separately fetched')),tag+': '+mode+' original/supplementary context labelled');
  await page.locator('#parameters > summary').click();
  const params=await page.locator('#parameters').innerText();
  check(!params.includes('Minimum swing move')&&!params.includes('Use optional Fib filter'),tag+': '+mode+' no invented parameter');
  if(mode==='fib'){
   check(await page.locator('#parameters input[type=checkbox]').count()===5,tag+': all five existing Fib-level choices retained');
   check(await page.locator('#parameters input[type=checkbox]:checked').count()===2,tag+': source default38.2/61.8levels selected');
  }
  await layout(page,tag+' '+mode);
  if(width===1366)await snap(page,tag+'-'+mode);
 }
 await page.locator('#breakdown-toggle').click();
 check(await page.locator('#filter-breakdown').isVisible(),tag+': saved report is reachable without scan');
 await page.locator('#stock-news > summary').click();
 check(await page.locator('#stock-news').innerText().then(t=>t.includes('publisher')&&t.includes('Tagged AAPL')&&t.includes('Industry news unavailable')),tag+': full news fields and limitation retained');
 await page.locator('#example-state').selectOption('unavailable');
 check(!(await page.locator('#scan-context').innerText()).includes('Supplementary live sample price'),tag+': missing context does not retain a live quote');
 await page.locator('#example-state').selectOption('empty');
 check(await page.locator('.candidate-row').count()===0,tag+': empty result state');
 check(!(await page.locator('#scan-context').innerText()).includes('$200.00'),tag+': no stale quote in empty context');
 await page.getByRole('button',{name:'Run Scan · example',exact:true}).click();
 check(await page.locator('.candidate-row').count()===3,tag+': fixed example restores sample rows');
 await page.getByRole('button',{name:'Open AAPL chart',exact:true}).click();
 check(await page.locator('#dialog').isVisible(),tag+': existing chart action preview');
 await page.getByRole('button',{name:'Close preview dialog',exact:true}).click();
 await page.locator('.candidate-row').first().getByRole('button',{name:'Alert',exact:true}).click();
 check(await page.getByRole('button',{name:'Save alert · preview only',exact:true}).isDisabled(),tag+': no real alert submission');
 await context.close();
}
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:args.browser,args:['--no-sandbox']});
 try{for(const width of [1200,1366,1920])for(const theme of ['dark','light']){process.stdout.write(`${width} ${theme}\n`);await stocks(browser,width,theme);await scanner(browser,width,theme)}}
 finally{await browser.close();fs.writeFileSync(path.join(out,'browser-checks.json'),JSON.stringify(report,null,2)+'\n')}
 check(report.pageErrors.length===0,'No browser page errors');check(report.networkRequests.length===0,'No API or outbound network requests; only static preview documents');
 fs.writeFileSync(path.join(out,'browser-checks.json'),JSON.stringify(report,null,2)+'\n');
 process.stdout.write(`${report.checks.length} checks passed; ${report.pageErrors.length} page errors; ${report.networkRequests.length} network requests\n`);
})().catch(e=>{console.error(e);process.exit(1)});
