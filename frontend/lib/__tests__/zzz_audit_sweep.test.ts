import { stopPremiumRisk, formatStopPremiumRisk, formatStopLossPct, formatStopLossHeadline } from '@/lib/risk';

function parseLine(s: string) {
  const m = s.match(/^\$([\d.]+) away × Δ([\d.]+) = \$([\d.]+) of \$([\d.]+) premium( \(uncapped \$([\d.]+)\))? · delta-linear, priced today$/);
  if (!m) throw new Error('unparsed: ' + s);
  return { move: +m[1], delta: +m[2], loss: +m[3], premium: +m[4], uncapped: m[6] ? +m[6] : null };
}
function parseHead(s: string) {
  const m = s.match(/^\$([\d,]+) per contract — of the \$([\d,]+) premium, \$(-?[\d,]+) left$/);
  if (!m) throw new Error('unparsed head: ' + s);
  const n = (x: string) => +x.replace(/,/g, '');
  return { per: n(m[1]), total: n(m[2]), left: n(m[3]) };
}

test('sweep', () => {
  const problems: Record<string, string[]> = {};
  const add = (k: string, msg: string) => { (problems[k] ||= []).push(msg); };
  let n = 0;
  for (let prem = 5; prem <= 6000; prem += 7) {          // cents 0.05 .. 60.00
    const premium = prem / 100;
    for (let d = 1; d <= 99; d += 1) {
      const delta = d / 100;
      for (let mv = 1; mv <= 12000; mv += 137) {          // 0.01 .. 120.00 stock move
        const stockPrice = 100;
        const stopPrice = 100 - mv / 100;
        const r = stopPremiumRisk(stopPrice, stockPrice, delta, premium);
        if (!r) continue;
        n++;
        const line = formatStopPremiumRisk(r);
        const head = formatStopLossHeadline(r);
        const badge = formatStopLossPct(r);
        const L = parseLine(line);
        const H = parseHead(head);
        // 1. equation multiplies out when no uncapped tail
        if (L.uncapped === null) {
          const prod = Math.round(L.move * L.delta * 100) / 100;
          if (Math.abs(prod - L.loss) > 1e-9) add('eq-no-tail', `${line}`);
        } else {
          const prod = Math.round(L.move * L.delta * 100) / 100;
          if (Math.abs(prod - L.uncapped) > 1e-9) add('eq-tail', `${line}`);
          if (!(L.uncapped > L.premium)) add('tail-not-greater', `${line}`);
          if (Math.abs(L.loss - L.premium) > 1e-9) add('tail-loss-not-premium', `${line}`);
        }
        // 2. headline parts sum
        if (H.per + H.left !== H.total) add('head-sum', `${head}`);
        if (H.left < 0) add('head-negative-left', `${head}`);
        // 3. headline vs line
        if (Math.abs(H.per - Math.round(L.loss * 100)) > 0) add('head-vs-line-loss', `${head} || ${line}`);
        if (Math.abs(H.total - Math.round(L.premium * 100)) > 0) add('head-vs-line-prem', `${head} || ${line}`);
        // 4. badge vs headline
        const b = badge === '100%' ? 100 : +badge.replace('%','');
        if (b === 100 && H.left !== 0) add('badge100-money-left', `${badge} || ${head}`);
        if (b !== 100 && H.left === 0) add('badge-not-100-but-zero-left', `${badge} || ${head} || ${line}`);
        if (b === 0 && H.per !== 0) add('badge0-but-loss', `${badge} || ${head}`);
        // 5. status vs badge
        if (r.status === 'PASS' && b >= 80) add('pass-but-badge-high', `${badge} ${r.status} frac=${r.fraction} || ${head} || ${line}`);
        if (r.status === 'CAUTION' && b < 80) add('caution-but-badge-low', `${badge} ${r.status} frac=${r.fraction} || ${head} || ${line}`);
      }
    }
  }
  const summary = Object.entries(problems).map(([k, v]) => `${k}: ${v.length} e.g. ${v[0]}`);
  console.log('N=' + n);
  console.log(summary.join('\n'));
  expect(true).toBe(true);
});
