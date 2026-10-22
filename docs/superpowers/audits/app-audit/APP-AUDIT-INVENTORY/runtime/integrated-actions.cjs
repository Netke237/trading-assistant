module.exports=async({page,goto,capture,attempt,json,surface})=>{
 await goto('/dashboard');
 const rows=['AAPL','MSFT'].map((symbol,i)=>({symbol,price:150+i,company:symbol+' synthetic fixture',direction:'Bullish',confidence:75-i,stock_score:70-i,stock_status:'CAUTION',metrics:{atr_ratio:.7+i/10,vol_ratio:.8,proximity_pct:2,custom:{zero:0,enabled:false,missing:null}},fib_swing:{low:100+i,high:120+i},fib_level_hit:'61.8',fib_dist_pct:1,at_level:true,strategy:{entry_price:150+i,stop_price:145+i,target_price:160+i,targets:[160+i],rr_ratio:2,atr:3,detail:{}},custom_evidence:{fixture:'integrated-'+symbol,entries:[0,false,null]}}));
 await json('/api/scan/prebreakout',rows);await json('/api/scan/fib-pullback',rows);await json('/api/stock-scan',{scan_id:'integrated-pullback',timestamp:'2026-10-16T08:00:00Z',candidates:rows,rejected:[]});
 await page.evaluate(()=>sessionStorage.setItem('audit-next-scan-seed',JSON.stringify({version:19,state:{screenerMode:'prebreakout',context:{universe:'Custom',direction:'Bullish',horizon:'Swing (5-20d)',holdMin:5,holdMax:20}}})));
 await goto('/screener/step-4-prebreakout');
 for(const [mode,label] of [['prebreakout','Pre-Breakout'],['pullback',/^Pullback to EMA/],['fib','Fib Pullback']])await attempt('integrated:'+mode,async()=>{
 await page.getByRole('button',{name:label,exact:typeof label==='string'}).last().click();await page.locator('textarea').first().fill('AAPL,MSFT');await page.getByRole('button',{name:'Run Scan',exact:true}).click();await page.getByText('MSFT',{exact:true}).first().waitFor();
 for(const symbol of ['AAPL','MSFT']){
 await page.getByText(symbol,{exact:true}).first().click();const region=page.getByRole('region',{name:'Evidence for '+symbol,exact:true});await region.waitFor();const outer=region.locator('details').first();if(!await outer.evaluate(n=>n.open))await outer.locator(':scope > summary').click();
 const raw=region.locator('details').filter({has:page.locator(':scope > summary').filter({hasText:'Raw data: complete returned evidence'})}).last();
 if(await raw.evaluate(n=>n.open))throw Error('raw disclosure carried open state across row');
 await raw.locator(':scope > summary').click();await raw.locator('pre').waitFor({state:'visible'});const value=JSON.parse(await raw.locator('pre').textContent());if(value.symbol!==symbol||value.custom_evidence.fixture!=='integrated-'+symbol)throw Error('wrong raw row');
 await capture(page,`integrated:${mode}:${symbol}:raw-open`,{surface_ids:[surface('SelectedRowEvidence'),surface('RawEvidence')],fixture_identity:`setup:${mode}:${symbol}`,assertion:'actual nested raw disclosure open; parsed raw symbol and fixture identity match current selected row',raw_value:value});
 await raw.locator(':scope > summary').click();if(await raw.evaluate(n=>n.open))throw Error('raw failed to close');await capture(page,`integrated:${mode}:${symbol}:raw-closed`,{surface_ids:[surface('RawEvidence')],fixture_identity:`setup:${mode}:${symbol}`,assertion:'actual nested raw close hides pre'});
 // Reopen before switching so next selection tests reset/remount behavior.
 await raw.locator(':scope > summary').click();
 }
 });
};
