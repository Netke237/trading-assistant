module.exports = async function extras(h) {
  const {page,goto,mode,capture,attempt,settled,storage,json,surface,expandDetails,heading,idFor,seed,inventory}=h;
  await attempt('tuning:restored-proposal',async()=>{
    const proposal={strategy:'pullback_ema',direction:'Bullish',proposed:{pullback_tolerance_pct:.04,ema_period:20},consistency:.75,eligible:true,oos_metrics:{sharpe:.9,n_trades:12,n_symbols:2,win_rate:.6,expectancy:.2,total_return_pct:5,max_drawdown_pct:3},fold_winners:[{fold:'audit-fold-A',ema_period:20},{fold:'audit-fold-B',ema_period:21}],verdict:{in_sample_return:8,walk_forward_return:5,degradation_pct:.375},recommendation:'Synthetic proposal for inventory disclosure only'};
    await json('/api/strategy-tuning/jobs/audit-tuning-job',{status:'completed',done:1,total:1,proposals:{pullback_ema:proposal}});
    await json('/api/strategy-tuning/jobs',{count:1,completed:1,failed:0,running:0});
    await goto('/settings');await page.evaluate(()=>sessionStorage.setItem('bamendjou:wfo:jobId','audit-tuning-job'));await page.reload();await settled(page);
    await page.locator('aside button').filter({has:page.getByText('Strategy Tuning',{exact:true})}).click();await page.getByRole('button',{name:/2 fold winners/}).waitFor();
    const before=await storage(page);await page.getByRole('button',{name:/2 fold winners/}).click();await page.getByText('audit-fold-A',{exact:true}).waitFor();await page.getByText('audit-fold-B',{exact:true}).waitFor();
    await capture(page,'tuning:expanded-two-folds',{surface_ids:[surface('ProposalCard')],native_ids:idFor('ProposalCard','button','fold winners'),fixture_identities:['job:audit-tuning-job','proposal:pullback_ema','fold:audit-fold-A','fold:audit-fold-B'],storage_before:before,assertion:'restored synthetic session job mocked GET creates proposal; actual accordion exposes two fold rows; no Run/Adopt action'});
  });
  await attempt('chart:imperative-nested',async()=>{
    await goto('/chart');
    const canvases=await page.locator('canvas').count();if(!canvases)throw Error('no imperative chart canvases');
    const box=await page.locator('canvas').first().boundingBox();if(box){await page.mouse.move(box.x+box.width*.6,box.y+box.height*.4);await page.mouse.click(box.x+box.width*.6,box.y+box.height*.4);}
    await capture(page,'chart:canvas-click-crosshair',{surface_ids:[surface('ChartWorkspace'),surface('ChartPane')].filter(Boolean),fixture_identity:'chart:AAPL:default-interval',assertion:'actual canvas exists; pointer move/click executed, DOM readback recorded; chart arithmetic pending H'});
    await page.keyboard.press('Escape');await page.getByRole('button',{name:'Indicators',exact:true}).click();await page.getByPlaceholder('Search…').waitFor();
    await capture(page,'chart:indicator-panel',{surface_ids:inventory.definitions.filter(d=>d.component==='IndicatorPanel'&&d.source.includes('/organisms/')).map(d=>d.id),assertion:'actual Indicators button reveals panel search'});
    await page.getByRole('button',{name:/^SMA/}).last().click();await capture(page,'chart:indicator-added',{fixture_identity:'indicator-type:SMA',assertion:'synthetic local SMA selection, actual panel readback; numerical outputs pending H'});
    const down=page.getByText('SMA',{exact:true}).first().locator('..').getByRole('button',{name:'▼',exact:true});if(await down.count()){await down.click();await page.getByText('Period',{exact:true}).waitFor();await capture(page,'chart:indicator-params',{fixture_identity:'indicator-type:SMA/param:period',assertion:'actual indicator expand reveals Period input'});}
    await goto('/chart');await page.getByRole('button',{name:'Structure',exact:true}).click();await capture(page,'chart:structure-panel',{surface_ids:[surface('StructurePanel')],assertion:'actual Structure button clicked and resultant DOM captured'});
    await goto('/chart');await page.getByRole('button',{name:'Alerts',exact:true}).first().click();await page.getByPlaceholder('e.g. AAPL breakout').waitFor();await capture(page,'chart:alert-builder',{surface_ids:[surface('AlertRuleBuilder')],assertion:'actual chart Alerts reveals nested builder, no Save'});
  });
  await attempt('tooltips:css-hover-focus',async()=>{
    await goto('/settings');await page.locator('aside button').filter({has:page.getByText('Scan',{exact:true})}).click();
    let tooltips=page.getByRole('tooltip',{includeHidden:true});if(!await tooltips.count()){await goto('/dev/components');tooltips=page.getByRole('tooltip',{includeHidden:true});}
    if(!await tooltips.count())throw Error('no Tooltip occurrence in attempted fixtures');
    const tip=tooltips.first();const wrap=tip.locator('..');const before=await tip.isVisible();await wrap.hover();await tip.waitFor({state:'visible'});
    await capture(page,'tooltip:css-hover',{surface_ids:[surface('Tooltip')],native_ids:idFor('Tooltip','span','{text}'),fixture_identity:'tooltip:'+await tip.textContent(),assertion:'actual CSS hover changes hidden tooltip to visible',visible_before:before});
    await page.mouse.move(0,0);const focus=wrap.locator('button,a,input,[tabindex]').first();if(await focus.count()){await focus.focus();await tip.waitFor({state:'visible'});await capture(page,'tooltip:css-focus',{surface_ids:[surface('Tooltip')],assertion:'actual focus-within tooltip visibly rendered'});}
  });
  await attempt('setup:populated-row-disclosures',async()=>{
    const rows=['AAPL','MSFT'].map((symbol,index)=>({symbol,direction:'Bullish',confidence:75-index,metrics:{atr_ratio:.7,vol_ratio:.8,proximity_pct:2},fib_swing:{low:100,high:120}}));
    await json('/api/scan/prebreakout',rows);
    await seed({screenerMode:'prebreakout',context:{universe:'Custom',direction:'Bullish',horizon:'Swing (5-20d)',holdMin:5,holdMax:20}});await goto('/screener/step-4-prebreakout');await page.getByRole('button',{name:'Run Scan',exact:true}).click();
    await page.getByText('AAPL',{exact:true}).first().waitFor();await page.getByText('MSFT',{exact:true}).first().waitFor();
    await capture(page,'setup:two-fixture-rows',{surface_ids:[surface('Step4PreBreakoutPage')],fixture_identities:['setup:prebreakout:AAPL','setup:prebreakout:MSFT'],assertion:'actual UI action resolves synthetic scan HTTP response entirely in browser; no backend job/request;2 distinct rows visible'});
    await page.getByText('AAPL',{exact:true}).first().click();await capture(page,'setup:selected-row',{surface_ids:[surface('SelectedRowEvidence'),surface('SelectedSetupChart')],fixture_identity:'setup:prebreakout:AAPL',assertion:'actual row selection opens selected chart/evidence; unknown applied snapshot shown honestly'});await expandDetails('setup:selected');
    await page.getByRole('button',{name:'Alert',exact:true}).first().click();await page.getByRole('dialog',{name:'Set regime alert for AAPL'}).waitFor();
    await capture(page,'setup:composite-alert',{surface_ids:[surface('CompositeAlertDialog')],fixture_identity:'setup:prebreakout:AAPL',assertion:'actual inline Alert opens symbol-specific composite dialog; no Save'});
    await page.getByRole('dialog').locator('select').filter({has:page.locator('option[value="HMM_intraday"]')}).selectOption('HMM_intraday');
    await capture(page,'setup:composite-intraday',{surface_ids:[surface('CompositeAlertDialog')],fixture_identity:'setup:prebreakout:AAPL/model:HMM_intraday',assertion:'actual model selection reveals nested intraday interval controls'});
    await page.getByRole('button',{name:'Close',exact:true}).click();
  });
  await attempt('reports:nested-fixture',async()=>{
    const report={category:'prebreakout',run_id:'audit-report-run',generation:1,trigger:'synthetic-fixture',started_at:'2026-10-12T08:00:00Z',ended_at:'2026-10-12T08:01:00Z',status:'completed',persistence:'saved',inputs:{request:{symbols:['AAPL','MSFT'],direction:'Bullish'},effective_configuration_complete:false},diagnostics_available:false,diagnostics:{accepted_symbols:['AAPL'],excluded:[{symbol:'MSFT',reason:'Synthetic exclusion'}]},result:{candidates:[{symbol:'AAPL',direction:'Bullish',confidence:75,metrics:{atr_ratio:.7,vol_ratio:.8,proximity_pct:2}}]}};
    await json('/api/scan-reports/latest/prebreakout',{category:'prebreakout',latest_attempt:report,previous_report:null});await json('/api/scan-reports/legacy',[]);
    await mode('prebreakout');await goto('/screener/step-4-prebreakout');await page.getByRole('button',{name:'Filter breakdown',exact:true}).click();
    await page.getByRole('region',{name:'Saved scan report',exact:true}).getByRole('heading',{name:'Run audit-report-run'}).waitFor();
    await capture(page,'report:filter-breakdown',{surface_ids:[surface('SavedScanReportInspector')],fixture_identity:'report:audit-report-run',assertion:'actual Filter breakdown reveals saved mock report with frozen configuration provenance'});await expandDetails('report:fixture');
    await page.getByRole('combobox',{name:'Report category'}).selectOption('legacy');await page.getByText('No legacy evidence available.',{exact:true}).waitFor();await capture(page,'report:legacy-empty',{surface_ids:[surface('SavedScanReportInspector')],fixture_identity:'report-category:legacy',assertion:'actual legacy selector shows empty legacy fixture; no category inferred'});
  });
  await attempt('boundary:position-card-minwidth',async()=>{await mode('stocks');await goto('/screener/step-7-position-card');for(const width of[1199,1200]){await page.setViewportSize({width,height:1000});await page.waitForTimeout(150);const visible=await page.getByRole('dialog',{name:'Desktop required'}).isVisible();if(visible!==(width<1200))throw Error('position minwidth mismatch');await capture(page,'min-width:position-card:'+width,{surface_ids:[surface('MinWidthGate')],assertion:'actual Desktop required visible='+visible});}await page.setViewportSize({width:1440,height:1000});});
};
