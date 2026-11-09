// Standalone reference verification. No app API, broker, provider or notification calls.
const fs = require('fs');
const path = require('path');
const assert = require('assert');
const root = path.resolve(__dirname, '../../../..');
const { chromium } = require(require.resolve('playwright', { paths: [path.join(root, 'frontend')] }));
(async () => {
 const browser = await chromium.launch({headless:true,executablePath:process.argv[2] || '/usr/bin/chromium',args:['--no-sandbox']});
 const page = await browser.newPage({viewport:{width:1366,height:1000},deviceScaleFactor:1});
 const errors=[], requests=[];
 page.on('pageerror', e=>errors.push(e.message));
 await page.route('**/*',r=>{requests.push(r.request().url());return r.abort();});
 let html=fs.readFileSync(path.join(__dirname,'preview.html'),'utf8');
 html=html.replace('<link rel="stylesheet" href="reference.css">',()=>'<style>'+fs.readFileSync(path.join(__dirname,'reference.css'),'utf8')+'</style>');
 html=html.replace('<script src="reference.js"></script>',()=>'<script>'+fs.readFileSync(path.join(__dirname,'reference.js'),'utf8')+'</script>');
 const evidence=path.join(__dirname,'evidence');fs.mkdirSync(evidence,{recursive:true});
 try{
 await page.setContent(html);
 assert(await page.locator('.sentiment + #fundamentals').count()===1);
 assert(await page.locator('.method:not(.hidden)').count()===1);
 assert(await page.locator('#mc').isVisible());
 assert(await page.locator('#exitexplanation').getAttribute('open')===null);
 const initial=await page.locator('#mc').boundingBox();
 await page.screenshot({path:path.join(evidence,'reference-initial.png'),fullPage:true});
 await page.getByRole('button',{name:'Run Monte Carlo Estimate',exact:true}).click();
 await page.getByRole('button',{name:'Compare',exact:true}).click();
 await page.getByRole('button',{name:'Compute Arithmetic Plan',exact:true}).click();
 assert(await page.locator('#mcstopcontext').isHidden());
 await page.getByRole('button',{name:'Run Monte Carlo Estimate',exact:true}).click();
 assert(await page.locator('#mcstockstop').innerText()==='$194.00');
 const cards=await page.locator('.method:not(.hidden)').evaluateAll(es=>es.map(e=>({id:e.id,width:e.getBoundingClientRect().width,height:e.getBoundingClientRect().height})));
 assert(Math.abs(cards[0].height-cards[1].height)<=1);
 const targetTops=await page.locator('#mcresults .tablewrap,#arithresults .tablewrap').evaluateAll(es=>es.map(e=>e.getBoundingClientRect().top));
 assert(Math.abs(targetTops[0]-targetTops[1])<=1,'target headers share comparison baseline');
 await page.getByRole('button',{name:'Ladder',exact:true}).first().click();
 assert(await page.locator('.method:not(.hidden)').count()===3);
 await page.getByRole('button',{name:'Ladder',exact:true}).first().click();
 await page.locator('.pickbutton[data-method="mc"]').click();
 assert(await page.locator('.targetchoice').count()===3);
 await page.locator('.targetchoice').nth(1).click();
 await page.getByRole('spinbutton',{name:'Contracts',exact:true}).fill('2');
 assert(await page.locator('#reviewprofit').innerText()==='$400.00');
 assert(await page.locator('#reviewvalue').innerText()==='$1,400.00');
 await page.screenshot({path:path.join(evidence,'reference-comparison.png'),fullPage:true});
 await page.locator('.methods').screenshot({path:path.join(evidence,'reference-methods.png')});
 await page.locator('#execution').screenshot({path:path.join(evidence,'reference-decision.png')});
 await page.locator('#racepanel > summary').click();
 assert(await page.locator('.racebar').count()===3);
 const splits=await page.locator('.racebar').evaluateAll(es=>es.map(e=>Array.from(e.children).map(x=>Number(x.style.width.replace('%','')))));
 splits.forEach(v=>assert(v.reduce((a,b)=>a+b,0)===100));
 await page.locator('#racepanel').screenshot({path:path.join(evidence,'reference-race.png')});
 await page.locator('#racepanel > summary').click();
 await page.locator('#pin-preview').click();
 for(const invalid of ['2.5','-1','0','101']){await page.getByRole('spinbutton',{name:'Contracts',exact:true}).fill(invalid);await page.getByRole('button',{name:'Review basket tracking',exact:true}).click();assert(!await page.locator('#destination-dialog').isVisible());assert((await page.locator('#review-error').innerText()).includes('whole number'));}
 await page.getByRole('spinbutton',{name:'Contracts',exact:true}).fill('2');
 await page.getByRole('button',{name:'Review basket tracking',exact:true}).click();
 assert((await page.locator('#destination-body').innerText()).includes('tracking only'));
 await page.locator('#destination-dialog').screenshot({path:path.join(evidence,'reference-basket-review.png')});
 // Check that the review is rejected if its settings change underneath it.
 await page.evaluate(()=>{document.getElementById('quantity').value='3';updateDecision();});
 await page.locator('#confirm-demo').click();
 assert((await page.locator('#destination-body').innerText()).includes('Settings changed since review'));
 await page.getByRole('button',{name:'Close review',exact:true}).click();
 await page.getByRole('spinbutton',{name:'Contracts',exact:true}).fill('2');
 await page.getByRole('button',{name:'Review broker limit order',exact:true}).click();
 assert((await page.locator('#destination-title').innerText()).includes('IBKR Paper'));
 assert((await page.locator('#destination-body').innerText()).includes('No protective stop-loss or take-profit order'));
 await page.locator('#destination-dialog').screenshot({path:path.join(evidence,'reference-broker-review.png')});
 await page.locator('#confirm-demo').click();
 assert((await page.locator('#destination-body').innerText()).includes('Nothing sent or saved'));
 await page.getByRole('button',{name:'Close review',exact:true}).click();
 await page.locator('.pickbutton[data-method="arith"]').click();
 assert(await page.locator('.targetchoice').count()===2);
 const copy=JSON.parse(fs.readFileSync(path.join(__dirname,'explanation-register.json'),'utf8'));
 let entryCount=0;
 for(const [key,id] of [['mc','mc'],['arithmetic','arith'],['ladder','ladder']]){
  const text=await page.locator('#copy-'+id).textContent();
  for(const item of copy[key]){assert(text.includes(item.text.replaceAll('\n',' ')),item.text);entryCount++;}
 }
 await page.getByRole('button',{name:'Light / dark',exact:true}).click();
 await page.screenshot({path:path.join(evidence,'reference-light.png'),fullPage:true});
 assert(errors.length===0,JSON.stringify(errors));assert(requests.length===0,JSON.stringify(requests));
 const result={viewport:{width:1366,height:1000},initialMethod:'mc',initialMethodBox:initial,comparison:cards,targetTops,threeMethods:true,mcTargets:3,arithmeticTargets:2,quantityTotals:true,staleRaceSuppressed:true,changedReviewRejected:true,trackingAndBrokerDemo:true,explanationEntries:entryCount,pageErrors:errors,networkRequests:requests};
 fs.writeFileSync(path.join(evidence,'reference-checks.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
