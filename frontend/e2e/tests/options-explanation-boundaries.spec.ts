import { test, expect, type Page } from '../fixtures';
import { MOCK_SCAN_CANDIDATE } from '../fixtures/api-mocks';

async function seed(page: Page, { iv = 34.01, pass = 34, caution = 55, event = { reject_days: 21, caution_days: 45 } }: { iv?: number; pass?: number; caution?: number | null; event?: { reject_days: number; caution_days: number } } = {}) {
  await page.route('**/api/config/iv-thresholds', r => r.fulfill({json: {
    Intraday: { abs_pass_max: null, abs_caution_max: null, rank_pass_max: null, rank_caution_max: null },
    Swing: { abs_pass_max: pass, abs_caution_max: caution, rank_pass_max: pass, rank_caution_max: caution },
    Position: { abs_pass_max: 44, abs_caution_max: 65, rank_pass_max: 44, rank_caution_max: 65 },
  }}));
  const candidate = {...MOCK_SCAN_CANDIDATE, nextEventDays: 50, contractDetails: {...MOCK_SCAN_CANDIDATE.contractDetails, ivRank: null, iv}};
  await page.addInitScript(([c,e]) => localStorage.setItem('bamendjou-scan-store',JSON.stringify({version:13,state:{
    scanResult:{scan_id:'review',timestamp:new Date().toISOString(),candidates:[c],rejected:[],event_window:e},
    context:{direction:'Bullish',horizon:'Swing (5-15d)'},scanState:'COMPLETED',scanAt:new Date().toISOString()
  }})), [candidate,event]);
  await page.goto('/screener/step-5-vol-events');
  await expect(page.locator('[data-testid="step-5"]')).toHaveAttribute('data-avail','ready');
}

test('AC2: expanded observation preserves 34.01 above a 34 ceiling',async({page})=>{
  await seed(page);
  await expect(page.locator('[data-cell="gate"]')).toHaveAttribute('data-gate','CAUTION');
  await page.getByRole('button',{name:'Explain gate details for AAPL'}).click();
  await expect(page.locator('[data-disclosure-panel]')).toContainText('34.01%');
});
test('AC2: header never promises CAUTION when its ceiling is null',async({page})=>{
  await seed(page,{iv:35,caution:null});
  await expect(page.locator('[data-cell="gate"]')).toHaveAttribute('data-gate','REJECT');
  await expect(page.locator('[data-part="iv-thresholds"]')).not.toContainText('CAUTION');
});
test('AC2: header explains unreachable CAUTION when IV ceilings coincide',async({page})=>{
  await seed(page,{iv:55,pass:55});
  await expect(page.locator('[data-cell="gate"]')).toHaveAttribute('data-gate','PASS');
  await expect(page.locator('[data-part="iv-thresholds"]')).toContainText('CAUTION: no reachable interval');
});
test('AC2: coincident event boundaries expose no reachable CAUTION interval',async({page})=>{
  await seed(page,{event:{reject_days:30,caution_days:30}});
  await expect(page.locator('[data-rules-strip]')).toContainText('CAUTION: no reachable interval');
});
test('AC7: every expanded text and control stays within its actual panel at 1280',async({page})=>{
  await page.setViewportSize({width:1280,height:800});
  await seed(page);
  await page.getByRole('button',{name:'Explain gate details for AAPL'}).click();
  const violations=await page.locator('[data-disclosure-panel]').evaluate(panel=>{
    const p=panel.getBoundingClientRect();
    return [...panel.querySelectorAll('*')].filter(el=>{
      const b=el.getBoundingClientRect();
      return b.width && (b.left<p.left-1||b.right>p.right+1);
    }).map(el=>({text:el.textContent,box:el.getBoundingClientRect().toJSON()}));
  });
  expect(violations).toEqual([]);
});
