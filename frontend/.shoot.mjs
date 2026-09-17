import { chromium } from '@playwright/test';

const OUT = '/tmp/claude-0/-home-user-trading-assistant/40753ad1-4d55-5ce6-9159-e6e6c8e12962/scratchpad/shots';
const KEY = 'bamendjou-scan-store', VERSION = 13;

// Real S&P names, deliberately including the long ones — a layout that only
// works on "Apple Inc." is not a layout that works.
const NAMES = [
  ['AAPL','Apple Inc.',185.2,82,null,42],
  ['MSFT','Microsoft Corporation',412.8,79,31,null],
  ['BRK.B','Berkshire Hathaway Inc. Class B',408.1,74,58,null],
  ['JPM','JPMorgan Chase & Co.',198.4,71,22,null],
  ['UNH','UnitedHealth Group Incorporated',521.7,68,null,47],
  ['PG','The Procter & Gamble Company',162.3,64,44,null],
  ['XOM','Exxon Mobil Corporation',114.9,61,null,39],
  ['NEE','NextEra Energy, Inc.',71.55,57,66,null],
];

const cand = ([symbol,company,price,score,ivRank,iv],i) => ({
  symbol, company, price, direction:'Bullish',
  status: score>=70?'PASS':score>=60?'CAUTION':'REJECT',
  stockScore: score, stockConfidence:'PASS',
  stockBreakdown:{trend:85,pullback:78,trigger:80,event:90,volatility:75},
  confidence: 60+i, confidenceText: 'backtested',
  rankDelta: i%3===0?2:i%3===1?-1:0, scoreDelta: i%2?3:-2,
  nextEventDays: [null,34,12,60,null,5,88,25][i],
  nextEventLabel: 'earnings',
  stopCostPct: [59.4,71.2,33.0,88.1,45.5,62.7,29.3,77.8][i],
  stopCostStatus: i%2?'CAUTION':'PASS',
  contract:`${symbol}|${Math.round(price)}|2025-05-16|C`,
  contractScore:78, contractConfidence:'PASS',
  contractBreakdown:{dteFit:80,delta:75,ivAttractiveness:70,liquidity:85,spread:80},
  contractDetails:{strike:Math.round(price),expiry:'2025-05-16',right:'C',mid:2.15,
    delta:0.52,theta:-0.05,ivRank,ivPercentile:ivRank,iv,dte:45},
  entry:{limit:2.1,maxFill:2.2,orderType:'Limit'},
  exit:{invalidation:price*0.97,premiumStop:1.0,timeStopDays:30,targets:[]},
});

const PAGES = [
  ['step-4-ranking','Options ranking (Step 4)'],
  ['step-5-vol-events','Volatility + Events (Step 5)'],
  ['step-6-contracts','Contracts (Step 6)'],
  ['step-7-trade-card','Trade card (Step 7)'],
];
const WIDTHS = [[1440,900,'1440-laptop'],[1920,1080,'1920-monitor']];

const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome' });
for (const [w,h,tag] of WIDTHS) {
  const ctx = await browser.newContext({ viewport:{width:w,height:h}, deviceScaleFactor:1 });
  await ctx.addInitScript(([key,version,candidates]) => {
    localStorage.setItem(key, JSON.stringify({ version, state:{
      scanResult:{ scan_id:'shot', timestamp:new Date().toISOString(), candidates, rejected:[] },
      scanState:'COMPLETED', scanAt:new Date().toISOString(),
      context:{ direction:'Bullish', horizon:'Swing (5-15d)', universe:'SP500' },
      screenerMode:'options',
    }}));
  }, [KEY, VERSION, NAMES.map(cand)]);
  const page = await ctx.newPage();
  for (const [slug,label] of PAGES) {
    await page.goto(`http://localhost:3001/screener/${slug}`, { waitUntil:'networkidle' }).catch(()=>{});
    await page.waitForTimeout(2500);
    const scroll = await page.evaluate(() => {
      const out = [];
      document.querySelectorAll('*').forEach(el => {
        if (el.scrollWidth > el.clientWidth + 1 && el.clientWidth > 200) {
          out.push({ cls: (el.className||'').toString().slice(0,60),
                     client: el.clientWidth, scroll: el.scrollWidth });
        }
      });
      return out;
    });
    await page.screenshot({ path:`${OUT}/${tag}--${slug}.png`, fullPage:false });
    console.log(`${tag} ${slug}: ${scroll.length} overflowing element(s)`);
    scroll.forEach(s => console.log(`    ${s.client}px visible / ${s.scroll}px content  [${s.cls}]`));
  }
  await ctx.close();
}
await browser.close();
console.log('done ->', OUT);
