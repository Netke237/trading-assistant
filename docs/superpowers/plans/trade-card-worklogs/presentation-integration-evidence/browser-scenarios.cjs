const fs=require('fs');
const ts=require(require.resolve('typescript',{paths:[process.cwd()]}));
const Module=require('module');
const {chromium}=require(require.resolve('playwright',{paths:[process.cwd()]}));
const fixturePath=require('path').resolve(process.cwd(),'e2e/fixtures/api-mocks.ts');
const fixtureMod=new Module(fixturePath);fixtureMod.filename=fixturePath;fixtureMod.paths=Module._nodeModulePaths(process.cwd());
fixtureMod._compile(ts.transpileModule(fs.readFileSync(fixturePath,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,fixturePath);
const fixture=fixtureMod.exports;
const card=JSON.parse(JSON.stringify(fixture.MOCK_SCAN_CANDIDATE).replaceAll('2025-05-16','2026-12-18'));
card.contractDetails.dte=75;card.exit.target=194.25;card.confidence=72;card.confidenceText='Historical entry signals: 64 samples.';
card.sentiment={horizon:'Swing',timeframe:'Daily',state:'Bullish',p_stay:0.73,stability:0.72,regime_age_days:8,avg_regime_duration:12,conviction_pct:73,conviction_label:'Bullish',interpretation:'Measured market context for this horizon.',alignment:'Aligned'};
card.fundamentals={score:74,quality_label:'Strong',risk_label:'Low',growth_score:80,quality_score:75,risk_score:65,safety_flags:['High debt'],detail:{}};
const race={premiumStopPrice:1.15,premiumStopPct:.465,stockStopPrice:180,premiumUsed:2.15,ivSolved:true,nPaths:2000,outcomes:[.2,.35,.5].map((pct,i)=>({targetPct:pct,targetOptionPrice:Number((2.15*(1+pct)).toFixed(2)),pTargetFirst:.4,pStockStopFirst:.2,pPremiumStopFirst:.3,pNeither:.1,weightTargetFirst:.4,weightStockStopFirst:.2,weightPremiumStopFirst:.3,weightNeither:.1,daysTarget:7+i*3,daysStockStop:8,daysPremiumStop:9,daysAnyPathReachedStop:10,repriceDaysStockStop:10,terminalMean:2,rewardDollar:Number((2.15*pct).toFixed(2)),stopRepricedValue:.65,riskStockStop:1.5,riskPremiumStop:1,rrStockStop:2.15*pct/1.5,rrPremiumStop:2.15*pct,edgePerContract:-30}))};
const first={targets:race.outcomes.map((o,i)=>({pct:o.targetPct,stockPrice:195+i*4,optionPrice:o.targetOptionPrice,probability:.5-i*.1,expectedDays:o.daysTarget})),invalidation:{probability:.3,expectedDays:10},race};
const exitPlan={stop:{price:180,source:'atr_widened',contractPrice:.65,rrModel:'Heston repriced',structuralSource:'order_block',structuralConfidence:75,structuralPrice:182,atrFloorPrice:180,distanceDollar:2},targets:[2,3].map((rr,i)=>({rrRatio:rr,arithmeticPrice:195+i*5,price:195+i*5,tpSource:'arithmetic',structuralPrice:null,contractPrice:3.7+i,rrModel:'Heston repriced',probability:.5-i*.1,expectedDays:9+i*4,qualityGood:true,qualityReasons:[],distanceDollar:null,toleranceDollar:1})),atr:4};

const scenario=process.env.SCENARIO;
let pickedContracts={},contractsBySymbol={};
if(scenario==='expired'){card.contractDetails.dte=0;first.race=null;}
if(scenario==='override'){const picked={...JSON.parse(JSON.stringify(fixture.MOCK_OPTION_CHAIN[1]).replaceAll('2025-05-16','2026-12-18')),dte:75,dteTotal:75};pickedContracts.AAPL=picked.id;contractsBySymbol.AAPL=[picked];}
if(scenario==='spread'){card.spreadType='bear_put';card.direction='Bearish';card.legs=[{action:'BUY',qty:1,strike:185,right:'P',expiry:'2026-12-18',bid:2,ask:2.3},{action:'SELL',qty:1,strike:180,right:'P',expiry:'2026-12-18',bid:1,ask:1.2}];card.netDebitCredit=1.05;card.maxProfit=395;card.maxLoss=105;card.breakeven=183.95;card.alternatives=[{symbol:'AAPL',strike:190,right:'P',expiry:'2026-12-18',dte:75,contractConfidence:'CAUTION',score:65,mid:3,delta:-.5,theta:-.04,ivRank:null,iv:42,rrRatio:2,reason:'Alternative expiry/strike trade-off',contractBreakdown:{dteFit:80,delta:70,ivAttractiveness:60,liquidity:70,spread:80}}];}
if(scenario==='evidence'){
 const path=require('path').resolve(process.cwd(),'components/molecules/TradeCardQualification/__tests__/evidence.test.tsx');
 const test=fs.readFileSync(path,'utf8');const constants=test.slice(test.indexOf('const card ='),test.indexOf("it('uses actual"));
 const module=new Module(path);module._compile(ts.transpileModule(constants+'\nmodule.exports={stock,contract};',{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,path);
 card.stockScore=54;card.stockConfidence='CAUTION';card.contractScore=0;card.contractConfidence='REJECT';card.finalStatus='REJECT';card.confidence=null;
 card.stockExplanation={...module.exports.stock,symbol:'AAPL'};card.contractExplanation={...module.exports.contract,contract_id:card.contract};
 first.race.ivSolved=false;first.race.outcomes[0].daysTarget=null;
}
(async()=>{
 const browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 const context=await browser.newContext({viewport:{width:1440,height:1100}});const page=await context.newPage();
 const errors=[];page.on('pageerror',e=>errors.push(e.message));const urls=new Set();
 await fixture.setupApiMocks(page);
 await page.route('**/api/**',async route=>{const path=new URL(route.request().url()).pathname;urls.add(path);let body;
 if(path.includes('/quote/stock')) body={symbol:'AAPL',price:185.2};
 else if(path.includes('/quote/option')) body={price:2.15,delta:.52,theta:-.05,ivRank:null,iv:42,spread:.02,volume:1250};
 else if(path.includes('/structural-stop')) body={available:true,price:180,source:'order_block',confidence:75,distancePct:2.8};
 else if(path.includes('/first-passage')) body=first;
 else if(path.includes('/recompute-plan')) {await new Promise(resolve=>setTimeout(resolve,750));body={entry:{limit:1.35,maxFill:1.5,orderType:'Limit'},exit:card.exit,rrRatio:2.8,rrModel:card.rrModel};}
 else if(path.includes('/auto-trade/status')) body={armed:false};
 else if(path.includes('/exit-plan')) body=exitPlan;
 else if(path.includes('/scan/last')||path.includes('/stocks/scan/last')) body=null;
 else {await route.fallback();return;}
 await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)});
 });
 await page.addInitScript(({card,pickedContracts,contractsBySymbol})=>{localStorage.setItem('bamendjou-settings',JSON.stringify({version:24,state:{ibkrPaper:{accountId:'fixture-account'}}}));localStorage.setItem('bamendjou-auto-trade',JSON.stringify({version:2,state:{selectedBroker:'ibkr_paper',autoMode:'manual'}}));localStorage.setItem('bamendjou-scan-store',JSON.stringify({version:17,state:{scanResult:{scan_id:'presentation-browser-fixture',timestamp:new Date().toISOString(),candidates:[card],rejected:[],contract_rules:{}},context:{universe:'SP500',direction:'Bullish',horizon:'Swing (5–15d)',horizonPreset:'Swing',holdMin:5,holdMax:15},scanState:'COMPLETED',scanAt:new Date().toISOString(),screenerMode:'options',pickedContracts,contractsBySymbol}}));},{card,pickedContracts,contractsBySymbol});
 await page.goto('http://127.0.0.1:3001/screener/step-7-trade-card');
 const results=[];const assert=(ok,label)=>{if(!ok)throw new Error(label);results.push(label)};
 if(scenario==='override'){
   await page.getByText('Preparing the plan for your selected contract…',{exact:true}).waitFor();
   assert(await page.getByText('Auto-trade mode',{exact:true}).count()===0,'override pending preserves original planReady AutoTradeArm gate');
   assert(await page.getByRole('radio',{name:'Ladder',exact:true}).count()===0,'override pending does not render old plan selector');
   await page.getByRole('button',{name:/Compute Arithmetic Plan/i}).waitFor();
   assert(await page.getByText('Auto-trade mode',{exact:true}).count()===1,'one original AutoTradeArm once override plan ready');
   assert(await page.getByText('AAPL|190|2026-12-18|C',{exact:true}).count()>0,'Step6 override displays selected identity');
   assert(await page.getByText('Not captured — re-run scan',{exact:true}).count()===2,'override missing evidence does not borrow original contract provenance');
 }else{
   await page.getByRole('button',{name:/Compute Arithmetic Plan/i}).waitFor();
   if(scenario==='spread'){
     assert(await page.getByText('Spread Legs — Bear Put Spread',{exact:true}).count()===1,'spread legs retain identity and summary');
     await page.getByRole('button',{name:/ALTERNATIVES/}).click();
     assert(await page.getByText('Alternative expiry/strike trade-off',{exact:true}).count()===1,'alternative metrics/reason reachable');
     assert(await page.getByText('Auto-trade mode',{exact:true}).count()===1,'spread retains original planReady AutoTradeArm rendering predicate');
   }else{
     await page.getByRole('button',{name:/Run Monte Carlo Estimate/i}).click();
     if(scenario==='expired'){
       await page.getByText(/Not simulated — contract expires today/).waitFor();
       assert(await page.getByRole('button',{name:/Use Barrier Race/}).count()===0,'expiry refusal has no race shortcut');
     }
     if(scenario==='evidence'){
       await page.getByRole('button',{name:'Use Barrier Race T20%'}).waitFor();
       assert(await page.getByText('Composite thresholds: PASS ≥ 54 · CAUTION ≥ 31',{exact:true}).count()===1,'actual custom stock thresholds retained');
       assert(await page.getByText(/Score forced to 0 by blocking rules/).count()===1,'contract hard rejection visible and diagnostic contributions qualified');
       assert(await page.getByText(/generic fallback volatility/).count()===1,'IV fallback warning remains active outside details');
       await page.getByText('Effective bounds, raw inputs and weighted losses',{exact:true}).click();
       assert(await page.getByText('min dte',{exact:true}).count()===1,'captured bound disclosure reachable');
     }
   }
 }
 fs.writeFileSync(`/tmp/integration-browser-${scenario}.json`,JSON.stringify({scenario,errors,results},null,2));
 await page.screenshot({path:`/tmp/integration-browser-${scenario}.png`});
 console.log(JSON.stringify({scenario,errors,results}));
 await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
