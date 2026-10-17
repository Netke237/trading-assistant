/* Additional fixture-driven runtime probes; imports only the isolated harness. */
module.exports = async function details(h) {
  const { page, goto, mode, capture, attempt, settled, storage, json, surface, inventory, MOCK_SCAN_CANDIDATE, results, write } = h;
  const expected = {
    '/dashboard': 'Dashboard', '/alerts': 'Alerts', '/analysis': 'Analysis', '/calendar': 'Calendar', '/journal': 'Trading Journal', '/portfolio': 'Portfolio', '/settings': 'Settings', '/strategy-watch': 'Strategy Watch', '/validation': 'Validation', '/watchlist': 'Watchlist',
    '/screener/step-1-regime': 'Market Regime', '/screener/step-2-universe': 'Universe', '/screener/step-3-direction': 'Direction', '/screener/step-4-ranking': 'Stock Ranking', '/screener/step-6-contracts': 'Contracts'
  };
  const idFor = (name, tag, text) => inventory.definitions.filter(d => !name || d.component === name).flatMap(d => d.native_surfaces).filter(n => (!tag || n.tag === tag) && n.text?.includes(text)).map(n => n.id);
  async function seed(state) { await page.evaluate(state => sessionStorage.setItem('audit-next-scan-seed', JSON.stringify({ version: 19, state })), state); }
  async function heading(text) { await page.getByRole('heading').filter({ hasText: new RegExp(text, 'i') }).first().waitFor(); }
  async function expandDetails(prefix, component) {
    const summaries = page.locator('details > summary');
    // Dynamic count after each expansion permits a nested child to be discovered.
    const seen = new Set();
    for (let index = 0; index < await summaries.count() && index < 60; index++) {
      const summary = summaries.nth(index); if (!await summary.isVisible()) continue;
      const label = (await summary.innerText()).trim(); if (seen.has(label)) continue; seen.add(label);
      await summary.click();
      const open = await summary.evaluate(n => n.parentElement.open); if (!open) continue;
      await capture(page, prefix + ':details:' + index, { surface_ids: component ? [surface(component)] : [], native_ids: idFor(component, 'summary', label), fixture_identity: prefix + '/summary:' + label, assertion: 'actual summary click opened parent details; nested content recorded', disclosure: label });
    }
  }
  await goto('/dashboard');
  await attempt('redirects:asserted', async () => {
    for (const [from,to,m] of [['/','/dashboard','options'],['/screener','/screener/step-1-regime','options'],['/screener/step-5-strategy','/screener/step-4-stocks','stocks']]) { await mode(m); await goto(from); await page.waitForURL('**' + to, { timeout: 45000 }); await capture(page, 'redirect:asserted:' + from, { requested_route_id: inventory.route_entries.find(r => r.route === from && r.classification === 'redirect').id, assertion: 'actual final URL equals ' + to }); }
  });
  await attempt('routes:semantic-dom', async () => {
    for (const [url,text] of Object.entries(expected)) await attempt('semantic:' + url, async () => { await mode('options'); await goto(url); await heading(text); await capture(page, 'semantic:' + url, { assertion: 'visible page heading matches ' + text }); });
  });
  await attempt('modes:ui-navigation', async () => {
    await mode('options'); await goto('/screener/step-1-regime');
    for (const [label,value,count] of [['Options','options',7],['Stocks','stocks',6],['Pre-Breakout','prebreakout',4]]) {
      await page.getByRole('button', { name: label, exact: true }).first().click();
      await page.getByRole('navigation', { name: 'Screener step navigation' }).getByText('STEP 1 OF ' + count, { exact: true }).waitFor();
      await capture(page, 'mode:button:' + value, { surface_ids: [surface('ScreenerLayout'),surface('StepNavBar')], fixture_identity: 'screener-mode:' + value, assertion: 'actual mode button changes logical step count to ' + count });
      await page.getByRole('navigation', { name: 'Screener step navigation' }).getByRole('button', { name: /^Next:/ }).click(); await page.waitForURL('**/step-2-universe'); await heading('Universe');
      await capture(page, 'mode:next:' + value, { assertion: 'Next button reaches Step2 under selected mode' });
      await page.keyboard.press('ArrowLeft'); await page.waitForURL('**/step-1-regime'); await capture(page, 'mode:keyboard-back:' + value, { assertion: 'ArrowLeft returns to Step1' });
    }
  });
  await attempt('setup:three-submodes', async () => {
    await mode('prebreakout'); await goto('/screener/step-4-prebreakout');
    for (const [label,sub,component] of [[/^Pre-Breakout$/,'prebreakout','PreBreakoutParamsPanel'],[/^Pullback to EMA/,'pullback','Step4PreBreakoutPage'],[/^Fib Pullback$/,'fib','FibPullbackParamsPanel']]) {
      const button = page.getByRole('button', { name: label }).last(); await button.click(); if (await button.getAttribute('aria-pressed') !== 'true') throw Error('submode did not activate');
      await heading(sub === 'pullback' ? 'Pullback candidates' : sub === 'fib' ? 'Fib Pullback candidates' : 'Pre-Breakout candidates');
      await capture(page, 'setup:submode:' + sub, { surface_ids: [surface('Step4PreBreakoutPage')], fixture_identity: 'setup-submode:' + sub, assertion: 'actual aria-pressed and matching candidates heading' });
      await expandDetails('setup:' + sub, component);
    }
  });
  await attempt('settings:deep-disclosures', async () => {
    await goto('/settings');
    for (const section of inventory.settings_sections) await attempt('settings:deep:' + section.key, async () => {
      const labels = { theme:'Appearance',scan:'Scan',strategy:'Strategy scan',brokers:'Brokers',risk:'Risk',regime:'Regime',notifications:'Notifications',data:'Data',tuning:'Strategy Tuning' };
      await page.locator('aside button').filter({ has: page.getByText(labels[section.key], { exact: true }) }).click();
      await settled(page); await capture(page, 'settings:section:' + section.key, { surface_ids: [surface(section.component)], native_ids: idFor('SettingsPage','button','{s.label}'), fixture_identity: 'settings-section:' + section.key, assertion: 'selected section actual DOM recorded', owners:{numeric:section.owner,persistence:'I',presentation:'J',navigation:'A'} });
      await expandDetails('settings:' + section.key, section.component);
    });
  });
  await attempt('shell:reject-confirmation', async () => {
    await mode('options');
    const reject = { overall:'REJECT',headline:'Synthetic reject fixture',metrics:[],omm:{state:'Bear',p_stay:.8,stability:'Stable',regime_age_days:4,avg_regime_duration:8,transition_row:[.1,.8,.1],state_order:['Bull','Bear','Choppy']} };
    await json('/api/regime',reject); await json('/api/regime?*',reject); await goto('/screener/step-1-regime');
    await page.locator('nav[data-regime="REJECT"]').waitFor(); await page.getByRole('button',{name:/^Next:/}).click();
    await page.getByRole('dialog',{name:'Regime flagged as REJECT'}).waitFor();
    const before=page.url(); await page.keyboard.press('ArrowRight'); if(page.url()!==before)throw Error('dialog failed arrow guard');
    await capture(page,'shell:reject-dialog',{surface_ids:[surface('StepNavBar')],native_ids:idFor('StepNavBar','div','Regime flagged'),assertion:'actual REJECT dialog visible and ArrowRight leaves URL unchanged'});
    await page.getByRole('button',{name:'Cancel',exact:true}).click(); if(await page.getByRole('dialog',{name:'Regime flagged as REJECT'}).count())throw Error('cancel failed');
    await capture(page,'shell:reject-cancel',{surface_ids:[surface('StepNavBar')],assertion:'Cancel dismisses confirmation; no navigation'});
    await page.getByRole('button',{name:/^Next:/}).click(); await page.getByRole('button',{name:/Proceed anyway/}).click(); await page.waitForURL('**/step-2-universe'); await capture(page,'shell:reject-proceed',{assertion:'Proceed reaches actual Step2 URL'});
  });
  await attempt('journal:fixture-nested',async()=>{
    const rows=['AAPL','MSFT'].map((symbol,index)=>({id:'audit-note-'+symbol,user_id:'synthetic',entry_type:'trade',entry_date:'2026-10-12T08:00:00Z',symbol,instrument_type:'stock',direction:'long',entry_price:100+index,exit_price:null,position_size:2,stop_loss:95,risk_dollars:10,net_pnl:null,thesis:'Synthetic inventory fixture',strategy_tag:'audit-fixture',mistake_tags:[],execution_grade:null,status:'open',lessons_learned:null,notes:'Synthetic fixture',position_id:null,r_multiple:null,created_at:'2026-10-12T08:00:00Z',updated_at:'2026-10-12T08:00:00Z'}));
    await json('/journal/entries*',rows); await goto('/journal'); await page.getByText('AAPL',{exact:true}).waitFor(); await page.getByText('MSFT',{exact:true}).waitFor();
    await capture(page,'journal:two-rows',{surface_ids:[surface('JournalEntryTable')],fixture_identities:rows.map(r=>r.id),assertion:'two distinct mocked journal rows visible'});
    await page.getByText('AAPL',{exact:true}).click(); await page.getByText('Edit entry',{exact:false}).first().waitFor(); await capture(page,'journal:edit-form',{surface_ids:[surface('JournalEntryForm')],fixture_identity:rows[0].id,assertion:'row click opens populated edit form'}); await expandDetails('journal:edit','JournalEntryForm');
  });
  await attempt('alerts:builder',async()=>{
    await goto('/alerts'); await page.getByRole('button',{name:'Rules',exact:true}).click(); await capture(page,'alerts:rules-tab',{surface_ids:[surface('AlertsPage')],assertion:'rules tab DOM recorded'});
    await page.getByRole('button',{name:'Create Alert',exact:true}).click(); await page.getByPlaceholder('e.g. AAPL breakout').waitFor();
    await page.getByRole('button',{name:'N of M',exact:true}).click(); await capture(page,'alerts:builder-n-of-m',{surface_ids:[surface('AlertRuleBuilder')],native_ids:idFor('AlertRuleBuilder','button','N of M'),assertion:'N of M actual button reveals threshold controls; no save'});
    const kind=page.locator('select').filter({has:page.locator('option[value="regime"]')}).first(); await kind.selectOption('regime'); await page.getByLabel('Regime model 1').waitFor(); await capture(page,'alerts:builder-regime-condition',{surface_ids:[surface('AlertRuleBuilder')],fixture_identity:'condition:initial-row:regime',assertion:'condition kind switch reveals model/state nested controls'});
    await page.getByRole('button',{name:'Close',exact:true}).click();
  });
  await attempt('options:populated-disclosures',async()=>{
    const candidate={...MOCK_SCAN_CANDIDATE,contract_rules:{min_volume:20}};
    await seed({screenerMode:'options',scanResult:{scan_id:'audit-options-fixture',timestamp:'2026-10-12T08:00:00Z',candidates:[candidate,{...candidate,symbol:'MSFT',company:'Microsoft fixture',contract:'MSFT|185|2025-05-16|C'}],rejected:[],contract_rules:{min_volume:20}},context:{universe:'Custom',direction:'Bullish',horizon:'Swing (5-20d)',holdMin:5,holdMax:20},scanState:'COMPLETED'});
    await goto('/screener/step-6-contracts'); await heading('Contracts'); const chain=page.getByRole('button',{name:/^AAPL.*contracts/});if(await chain.getAttribute('aria-expanded')!=='true')await chain.click();await page.getByRole('button',{name:/^Explain score for/}).first().waitFor(); await page.getByRole('button',{name:/^Explain score for/}).first().click(); await page.getByRole('region',{name:/Score explanation/}).first().waitFor();
    await capture(page,'options:contract-explanation',{surface_ids:[surface('ContractScoreExplanationContent')],fixture_identity:'AAPL|185|2025-05-16|C',assertion:'actual Explain reveals named Score explanation region; arithmetic pending C'}); await expandDetails('options:contracts');
    const before=await storage(page); await page.reload(); await settled(page); await heading('Contracts'); await capture(page,'options:reload-populated',{storage_before:before,fixture_identities:['AAPL','MSFT'],assertion:'reload actual Contracts DOM with persisted fixture; recovery responses recorded; arithmetic pending C/I'});
    await goto('/screener/step-7-trade-card'); await capture(page,'options:trade-card-populated',{surface_ids:[surface('TradeCard')],fixture_identities:['AAPL','MSFT'],assertion:'actual populated trade-card DOM recorded, no broker action'}); await expandDetails('options:trade-card','TradeCard');
  });
  await attempt('boundary:fixture-error-reset',async()=>{
    await json('/api/events',{invalid_fixture:'intentional wrong shape for page render throw'}); await goto('/calendar');
    await page.getByRole('heading',{name:'Something broke in this view.'}).waitFor();
    await capture(page,'boundary:frame-error',{surface_ids:[surface('FrameError')],assertion:'fixture-induced render failure visibly reached real Frame error boundary; not application defect'});
    await json('/api/events',[]); await page.getByRole('button',{name:'Retry',exact:true}).click(); await heading('Calendar'); await capture(page,'boundary:frame-reset',{surface_ids:[surface('FrameError')],assertion:'Retry after valid mock visibly restores Calendar'});
  });
  await attempt('boundary:frame-loading',async()=>{
    await goto('/dashboard');
    const delay=async route=>{await new Promise(resolve=>setTimeout(resolve,2500));await route.continue();};
    await page.route('**/journal?*',delay);
    await page.locator('nav[aria-label="Primary"] a[href="/journal"]').click();
    await page.getByRole('status').filter({hasText:/^Loading…$/}).waitFor({timeout:4000}); await capture(page,'boundary:frame-loading-visible',{surface_ids:[surface('Loading')],assertion:'actual frame Loading status visible during delayed frontend route stream'});
    await page.unroute('**/journal?*',delay); await heading('Trading Journal');
  });
  await attempt('slots:history-controlled',async()=>{
    await goto('/dashboard'); await heading('Dashboard'); const initial=await storage(page); await capture(page,'slots:dashboard-hard',{storage_before:initial,assertion:'hard dashboard rail actual content recorded'});
    for(const url of ['/portfolio','/calendar','/watchlist','/settings','/alerts','/analysis','/chart']){
      await page.locator('nav[aria-label="Primary"] a[href="'+url+'"]').click(); await page.waitForURL('**'+url); await settled(page); await capture(page,'slots:soft:'+url,{assertion:'actual primary link soft navigation; all aside text recorded'});
      const before=await storage(page); await page.reload(); await settled(page); await capture(page,'slots:hard:'+url,{storage_before:before,assertion:'same URL hard reload; compare rail with immediately preceding soft observation'});
    }
    await page.goBack();await settled(page);await capture(page,'slots:back',{assertion:'browser history back actual URL/rail/storage'});await page.goForward();await settled(page);await capture(page,'slots:forward',{assertion:'browser history forward actual URL/rail/storage'});
  });
  await require('./extras.cjs')({ ...h, seed, expandDetails, heading, idFor });
};
