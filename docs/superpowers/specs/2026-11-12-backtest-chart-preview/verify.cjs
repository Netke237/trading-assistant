// Browser checks for the standalone design reference. No app or broker endpoints.
const {chromium}=require('../../../../frontend/node_modules/playwright');
const {pathToFileURL}=require('node:url');
const path=require('node:path');
const fs=require('node:fs');
(async()=>{
 const browser=await chromium.launch({channel:'chrome',headless:true});
 const errors=[],requests=[];let checks=0;
 const ok=(value,message)=>{if(!value)throw new Error(message);checks++;};
 for(const width of [1366,1920,390]){
  const page=await browser.newPage({viewport:{width,height:1000}});
  page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>{if(!r.url().startsWith('file:'))requests.push(r.url());});
  await page.goto(pathToFileURL(path.join(__dirname,'index.html')).href);
  await page.getByRole('heading',{name:'Strategy versus buying & holding'}).waitFor();
  ok(await page.locator('#strategyValue').textContent()==='+9.59%','Strategy endpoint');
  ok(await page.locator('#benchmarkValue').textContent()==='+204.48%','Benchmark endpoint');
  ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'No horizontal page overflow');
  for(const theme of ['light','dark']){
   if(theme==='dark')await page.locator('#theme').click();
   await page.getByRole('button',{name:'OHLC bars',exact:true}).click();
   ok(await page.getByRole('button',{name:'OHLC bars',exact:true}).getAttribute('aria-pressed')==='true','Bar control');
   await page.getByRole('button',{name:'Line',exact:true}).click();
   await page.getByRole('button',{name:'Candles',exact:true}).click();
   await page.getByRole('button',{name:'Index 100',exact:true}).click();
   ok(await page.locator('#strategyValue').textContent()==='109.59','Index endpoint');
   await page.getByRole('button',{name:'Return %',exact:true}).click();
   await page.getByRole('button',{name:'Last year',exact:true}).click();
   ok((await page.locator('#rangeCaption').textContent()).includes('last year'),'Range caption');
   ok(await page.locator('#benchmarkValue').textContent()==='+204.48%','Range retains baseline');
   await page.getByRole('button',{name:'All history',exact:true}).click();
   await page.locator('#showBenchmark').uncheck();
   await page.locator('#showStrategy').uncheck();
   ok(await page.locator('#empty').isVisible(),'Empty series guidance');
   await page.locator('#showBenchmark').check();await page.locator('#showStrategy').check();
   await page.getByRole('button',{name:'Expand chart',exact:true}).click();
   await page.getByRole('button',{name:'Reduce chart',exact:true}).click();
   await page.getByRole('button',{name:'Inspect trade 1',exact:true}).click();
   ok((await page.locator('#selectionText').textContent()).includes('Trade #01'),'Trade selection');
   ok((await page.locator('#rangeCaption').textContent()).includes('selected trade'),'Linked range');
   await page.getByRole('button',{name:'Clear selection',exact:true}).click();
   await page.getByRole('button',{name:'Next',exact:true}).click();
   ok((await page.locator('#pageLabel').textContent()).includes('7–12'),'Trade pagination');
   await page.getByRole('button',{name:'Previous',exact:true}).click();
   await page.locator('#sort').selectOption('newest');
   ok((await page.locator('#trades tr').first().textContent()).includes('#24'),'Trade sorting');
   await page.locator('#sort').selectOption('date');
   await page.locator('#freshButton').click();ok(await page.locator('#fresh').isVisible(),'Fresh-run disclosure');await page.locator('#freshButton').click();
   await page.locator('#performance').scrollIntoViewIfNeeded();
   const box=await page.locator('#performance').boundingBox();
   await page.mouse.move(box.x+box.width*.5,box.y+80);
   ok(await page.locator('#performanceTip').isVisible(),'Chart tooltip');
   await page.mouse.move(0,0);
   await page.evaluate(()=>scrollTo(0,0));
   if(width!==390)await page.screenshot({path:path.join(__dirname,`preview-${width}-${theme}.png`),fullPage:true});
  }
  await page.close();
 }
 ok(errors.length===0,'No browser errors: '+errors.join('; '));ok(requests.length===0,'No network requests');
 const report={checks,pageErrors:errors,outboundRequests:requests,viewports:[1366,1920,390],themes:['light','dark'],note:'Synthetic standalone design preview, not application acceptance.'};
 fs.writeFileSync(path.join(__dirname,'verification.json'),JSON.stringify(report,null,2)+'\n');
 console.log(JSON.stringify(report));await browser.close();
})().catch(e=>{console.error(e);process.exit(1);});
