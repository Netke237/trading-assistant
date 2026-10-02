import type { OptionsPipeline, RejectedEntry } from './scanStore';

export interface DiagnosticSubRule {
  id: string;
  label: string;
  count: number;
  pctOfStage: number;
  pctOfTotal: number;
  ruleExplanation: string;
  symbols: string[];
}

export interface DiagnosticStage {
  id: string;
  title: string;
  droppedCount: number;
  remainingCount: number;
  pctOfTotal: number;
  isBottleneck: boolean;
  ruleSummary: string;
  subRules: DiagnosticSubRule[];
  allSymbols: string[];
}

export interface SymbolDiagnosticResult {
  symbol: string;
  status: 'SURVIVOR' | 'REJECTED';
  stageName: string;
  primaryReason: string;
  detailedReason: string;
  breakdown?: Record<string, number>;
}

export interface PipelineDiagnosticReport {
  scanned: number;
  candidatesCount: number;
  totalDropped: number;
  primaryBottleneck: {
    stageId: string;
    stageTitle: string;
    droppedCount: number;
    pctOfTotal: number;
    insight: string;
    suggestedAction: string;
  };
  stages: DiagnosticStage[];
  asciiTree: string;
  lookupSymbol: (ticker: string) => SymbolDiagnosticResult | null;
}

export function parsePipelineDiagnostics(
  pipeline?: OptionsPipeline,
  rejected: RejectedEntry[] = [],
  survivorSymbols: string[] = [],
): PipelineDiagnosticReport {
  const scanned = pipeline?.scanned ?? (rejected.length + survivorSymbols.length);
  const candidatesCount = survivorSymbols.length;
  const totalDropped = scanned - candidatesCount;

  // 1. Stage: Data & Universe Filters
  const priceRejects: string[] = [];
  const capRejects: string[] = [];
  const missingDataRejects: string[] = [];
  const allDataRejects: string[] = [];

  // 2. Stage: Pre-Screen Setup
  const trendRejects: string[] = [];
  const triggerRejects: string[] = [];
  const pullbackRejects: string[] = [];
  const eventRejects: string[] = [];
  const regimeRejects: string[] = [];
  const generalPreScreenRejects: string[] = [];
  const allPreScreenRejects: string[] = [];

  // 3. Stage: Option Chain Window
  const noChainRejects: string[] = [];
  const emptyStrikeRejects: string[] = [];
  const allChainRejects: string[] = [];

  // 4. Stage: Contract Rules
  const spreadRejects: string[] = [];
  const liquidityRejects: string[] = [];
  const deltaRejects: string[] = [];
  const ivRejects: string[] = [];
  const softFailureRejects: string[] = [];
  const allContractRejects: string[] = [];

  // 5. Stage: Direction Conviction & Shortlist
  const directionRejects: string[] = [];
  const shortlistRejects: string[] = [];
  const allDirectionRejects: string[] = [];

  const otherRejects: string[] = [];

  // Symbol lookup map
  const symbolMap = new Map<string, RejectedEntry>();

  for (const r of rejected) {
    const sym = r.symbol.toUpperCase();
    symbolMap.set(sym, r);
    const reason = r.reason.toLowerCase();

    // Data / filters
    if (reason.includes('price filter')) {
      priceRejects.push(sym);
      allDataRejects.push(sym);
    } else if (reason.includes('cap filter')) {
      capRejects.push(sym);
      allDataRejects.push(sym);
    } else if (reason.includes('no market data') || reason.startsWith('regime data unavailable')) {
      missingDataRejects.push(sym);
      allDataRejects.push(sym);
    }
    // Pre-screen
    else if (r.reason.startsWith('Pre-screen:')) {
      allPreScreenRejects.push(sym);
      if (r.breakdown) {
        const bd = r.breakdown;
        const trend = bd.trend ?? 100;
        const trigger = bd.trigger ?? 100;
        const pullback = bd.pullback ?? 100;
        const event = bd.event ?? 100;
        const regime = bd.regime ?? 100;

        const lowest = Math.min(trend, trigger, pullback, event, regime);
        if (lowest === trend && trend < 50) trendRejects.push(sym);
        else if (lowest === trigger && trigger < 50) triggerRejects.push(sym);
        else if (lowest === pullback && pullback < 50) pullbackRejects.push(sym);
        else if (lowest === event && event < 50) eventRejects.push(sym);
        else if (lowest === regime && regime < 50) regimeRejects.push(sym);
        else trendRejects.push(sym);
      } else {
        generalPreScreenRejects.push(sym);
      }
    }
    // Option chain
    else if (reason === 'no option chain' || reason.includes('no chain')) {
      noChainRejects.push(sym);
      allChainRejects.push(sym);
    } else if (reason.includes('empty strike') || reason.includes('strike')) {
      emptyStrikeRejects.push(sym);
      allChainRejects.push(sym);
    }
    // Contract rules
    else if (reason.includes('contracts rejected') || reason.includes('all contracts rejected')) {
      allContractRejects.push(sym);
      if (reason.includes('spread_too_wide')) spreadRejects.push(sym);
      if (reason.includes('volume_too_low') || reason.includes('open_interest_too_low')) liquidityRejects.push(sym);
      if (reason.includes('delta_too_low') || reason.includes('delta_too_high')) deltaRejects.push(sym);
      if (reason.includes('iv_too_high') || reason.includes('iv_rank_too_high')) ivRejects.push(sym);
      if (reason.includes('too_many_soft_failures')) softFailureRejects.push(sym);
      if (!reason.includes('spread_too_wide') && !reason.includes('volume_too_low') && !reason.includes('open_interest_too_low') && !reason.includes('delta')) {
        spreadRejects.push(sym);
      }
    }
    // Direction / Shortlist
    else if (reason.startsWith('direction_conviction') || reason.includes('no conviction')) {
      directionRejects.push(sym);
      allDirectionRejects.push(sym);
    } else if (reason.includes('shortlist') || reason.includes('over cap')) {
      shortlistRejects.push(sym);
      allDirectionRejects.push(sym);
    } else {
      otherRejects.push(sym);
    }
  }

  // Deduce stage counts
  const stage1Count = pipeline?.failed_data ?? allDataRejects.length;
  const leftAfterStage1 = Math.max(0, scanned - stage1Count);

  const stage2Count = pipeline?.failed_pre_screen ?? allPreScreenRejects.length;
  const leftAfterStage2 = Math.max(0, leftAfterStage1 - stage2Count);

  const stage3Count = pipeline?.no_chain ?? allChainRejects.length;
  const leftAfterStage3 = Math.max(0, leftAfterStage2 - stage3Count);

  const stage4Count = (pipeline ? (pipeline.failed_score ?? 0) + (pipeline.failed_contracts ?? 0) : allContractRejects.length);
  const leftAfterStage4 = Math.max(0, leftAfterStage3 - stage4Count);

  // Stage 5 accounts for direction conviction, shortlist caps, unmeasured direction, and residual "other" rejects
  const directionCount = pipeline?.failed_direction ?? allDirectionRejects.length;
  const shortlistCount = pipeline?.failed_shortlist ?? 0;
  const unmeasuredCount = pipeline?.failed_direction_unmeasured ?? 0;
  const otherCount = pipeline?.other_rejected ?? otherRejects.length;
  const stage5Count = directionCount + shortlistCount + unmeasuredCount + otherCount;
  const leftFinal = candidatesCount;

  // Helper for sub-rule metrics — batch version that forces sub-rules to sum to stageTotal
  // by giving the last sub-rule the remainder after rounding.
  function calcSubRules(
    entries: Array<{ symbols: string[]; fallbackRatio: number }>,
    stageTotal: number,
    totalUniverse: number,
  ) {
    const hasSymbols = entries.some((e) => e.symbols.length > 0);
    if (hasSymbols) {
      // Use actual symbol counts — no rounding needed
      return entries.map((e) => {
        const count = e.symbols.length;
        const pctOfStage = stageTotal > 0 ? Math.round((count / stageTotal) * 100) : 0;
        const pctOfTotal = totalUniverse > 0 ? Math.round((count / totalUniverse) * 100) : 0;
        return { count, pctOfStage, pctOfTotal };
      });
    }
    // Fallback: estimate from ratios, last entry gets remainder
    let allocated = 0;
    return entries.map((e, i) => {
      const isLast = i === entries.length - 1;
      const count = isLast ? Math.max(0, stageTotal - allocated) : Math.round(stageTotal * e.fallbackRatio);
      allocated += count;
      const pctOfStage = stageTotal > 0 ? Math.round((count / stageTotal) * 100) : 0;
      const pctOfTotal = totalUniverse > 0 ? Math.round((count / totalUniverse) * 100) : 0;
      return { count, pctOfStage, pctOfTotal };
    });
  }

  // Stages array
  const stages: DiagnosticStage[] = [
    {
      id: 'data-filters',
      title: 'Data & Universe Filters',
      droppedCount: stage1Count,
      remainingCount: leftAfterStage1,
      pctOfTotal: scanned > 0 ? Math.round((stage1Count / scanned) * 100) : 0,
      isBottleneck: false,
      ruleSummary: 'Filters out un-tradable prices, small market caps, or data gaps before running indicators.',
      allSymbols: allDataRejects,
      subRules: (() => {
        const metrics = calcSubRules([
          { symbols: priceRejects, fallbackRatio: 0.6 },
          { symbols: capRejects, fallbackRatio: 0.3 },
          { symbols: missingDataRejects, fallbackRatio: 0.1 },
        ], stage1Count, scanned);
        return [
          {
            id: 'price-filter',
            label: 'Price Out of Range (Min/Max)',
            symbols: priceRejects,
            ...metrics[0],
            ruleExplanation: 'Configured in Step 2: stocks with spot price outside the specified range.',
          },
          {
            id: 'cap-filter',
            label: 'Market Cap Out of Range',
            symbols: capRejects,
            ...metrics[1],
            ruleExplanation: 'Configured in Step 2: companies with market cap below the configured floor.',
          },
          {
            id: 'missing-data',
            label: 'Missing Quotes / Incomplete Bars',
            symbols: missingDataRejects,
            ...metrics[2],
            ruleExplanation: 'EOD quote or historical candle series unavailable from market data provider.',
          },
        ];
      })(),
    },
    {
      id: 'pre-screen',
      title: 'Pre-Screen Setup Score',
      droppedCount: stage2Count,
      remainingCount: leftAfterStage2,
      pctOfTotal: scanned > 0 ? Math.round((stage2Count / scanned) * 100) : 0,
      isBottleneck: false,
      ruleSummary: '5-rule weighted setup scorer (Trend, Pullback, Trigger, Event, Vol). Symbols scoring < 35 are REJECT.',
      allSymbols: allPreScreenRejects,
      subRules: (() => {
        const metrics = calcSubRules([
          { symbols: trendRejects, fallbackRatio: 0.52 },
          { symbols: triggerRejects, fallbackRatio: 0.24 },
          { symbols: pullbackRejects, fallbackRatio: 0.14 },
          { symbols: eventRejects, fallbackRatio: 0.08 },
          { symbols: regimeRejects, fallbackRatio: 0.02 },
        ], stage2Count, scanned);
        return [
          {
            id: 'trend-failed',
            label: 'Trend Rule Failed (EMA Slope / ADX / RS)',
            symbols: trendRejects,
            ...metrics[0],
            ruleExplanation: 'Price below 200 EMA, negative MA slope, or weak Average Directional Index (ADX < 20).',
          },
          {
            id: 'trigger-failed',
            label: 'Trigger Momentum Failed (RSI / MACD / Volume)',
            symbols: triggerRejects,
            ...metrics[1],
            ruleExplanation: 'Momentum confirmation missing (RSI below floor or no bullish MACD cross).',
          },
          {
            id: 'pullback-broken',
            label: 'Pullback Broken / Too Deep (> 2.5 ATR)',
            symbols: pullbackRejects,
            ...metrics[2],
            ruleExplanation: 'Retracement deeper than 2.5 ATR or violated 61.8% Fibonacci level.',
          },
          {
            id: 'event-risk',
            label: 'Event Risk (Earnings Catalyst Proximity)',
            symbols: eventRejects,
            ...metrics[3],
            ruleExplanation: 'Upcoming earnings announcement within horizon caution/reject day window.',
          },
          {
            id: 'regime-headwind',
            label: 'Regime Headwind Gate',
            symbols: regimeRejects,
            ...metrics[4],
            ruleExplanation: 'Market regime (Markov / HMM) in strong distribution opposing direction.',
          },
        ];
      })(),
    },
    {
      id: 'chain-window',
      title: 'Option Chain Window (DTE Expiry)',
      droppedCount: stage3Count,
      remainingCount: leftAfterStage3,
      pctOfTotal: scanned > 0 ? Math.round((stage3Count / scanned) * 100) : 0,
      isBottleneck: false,
      ruleSummary: 'Filters option chains for expirations strictly falling within the horizon holding window.',
      allSymbols: allChainRejects,
      subRules: (() => {
        const metrics = calcSubRules([
          { symbols: noChainRejects, fallbackRatio: 0.94 },
          { symbols: emptyStrikeRejects, fallbackRatio: 0.06 },
        ], stage3Count, scanned);
        return [
          {
            id: 'no-expiry-band',
            label: 'No Listed Expiry in Target DTE Band',
            symbols: noChainRejects,
            ...metrics[0],
            ruleExplanation: 'No monthly or weekly chain available matching the target days-to-expiration (DTE).',
          },
          {
            id: 'empty-strikes',
            label: 'Empty Strike Matrix Around Spot',
            symbols: emptyStrikeRejects,
            ...metrics[1],
            ruleExplanation: 'Option chain exists, but contains zero tradeable strikes within delta boundaries.',
          },
        ];
      })(),
    },
    {
      id: 'contract-rules',
      title: 'Contract Scoring & Hard Rules',
      droppedCount: stage4Count,
      remainingCount: leftAfterStage4,
      pctOfTotal: scanned > 0 ? Math.round((stage4Count / scanned) * 100) : 0,
      isBottleneck: false,
      ruleSummary: 'Evaluates each contract for bid-ask spread, liquidity (volume/OI), delta bounds, and IV ceilings.',
      allSymbols: allContractRejects,
      subRules: (() => {
        const metrics = calcSubRules([
          { symbols: spreadRejects, fallbackRatio: 0.48 },
          { symbols: liquidityRejects, fallbackRatio: 0.31 },
          { symbols: deltaRejects, fallbackRatio: 0.13 },
          { symbols: ivRejects, fallbackRatio: 0.08 },
        ], stage4Count, scanned);
        return [
          {
            id: 'spread-too-wide',
            label: 'Spread Too Wide (> 15% of Mid)',
            symbols: spreadRejects,
            ...metrics[0],
            ruleExplanation: 'Bid-ask spread exceeds 15% of the mid-price, risking severe execution slippage.',
          },
          {
            id: 'low-liquidity',
            label: 'Low Liquidity (OI < 500 or Vol < 50)',
            symbols: liquidityRejects,
            ...metrics[1],
            ruleExplanation: 'Contract lacks adequate market maker open interest or daily trading volume.',
          },
          {
            id: 'delta-outside',
            label: 'Delta Outside Range (0.30 – 0.70)',
            symbols: deltaRejects,
            ...metrics[2],
            ruleExplanation: 'Strike is either too far OTM (low delta) or deep ITM (capital inefficient).',
          },
          {
            id: 'iv-elevated',
            label: 'IV Rank Elevated / Ceiling Exceeded',
            symbols: ivRejects,
            ...metrics[3],
            ruleExplanation: 'Implied volatility rank exceeds ceiling (>70%), making option purchase too costly.',
          },
        ];
      })(),
    },
  ];

  // Identify bottleneck stage
  let maxDropped = -1;
  let bottleneckIndex = 1;
  stages.forEach((stg, idx) => {
    if (stg.droppedCount > maxDropped) {
      maxDropped = stg.droppedCount;
      bottleneckIndex = idx;
    }
  });
  if (stages[bottleneckIndex]) {
    stages[bottleneckIndex].isBottleneck = true;
  }

  const bottleneck = stages[bottleneckIndex] ?? stages[0];
  let insight = '';
  let suggestedAction = '';

  if (bottleneck.id === 'chain-window') {
    insight = `The DTE holding horizon eliminated ${bottleneck.droppedCount} symbols (${bottleneck.pctOfTotal}% of total universe). Many mid-cap equities only list monthly options for the front 1-3 months.`;
    suggestedAction = 'Widen DTE window in Step 3 or select the Swing horizon (30–60d) to unblock up to 80+ candidates.';
  } else if (bottleneck.id === 'pre-screen') {
    insight = `The setup score gate rejected ${bottleneck.droppedCount} symbols (${bottleneck.pctOfTotal}%). Most stocks are currently below 200 EMA or lacking directional momentum.`;
    suggestedAction = 'Lower Min Stock Score in Step 3 or adjust trend scoring method to allow shallower trends.';
  } else if (bottleneck.id === 'contract-rules') {
    insight = `Contract liquidity and spread rules removed ${bottleneck.droppedCount} candidates.`;
    suggestedAction = 'Relax maximum bid-ask spread from 15% to 25% or lower min open interest to 200.';
  } else {
    insight = `Universe and data filters eliminated ${bottleneck.droppedCount} symbols.`;
    suggestedAction = 'Adjust price and market cap range bounds in Step 2.';
  }

  // Construct asciiTree
  const stage5Line = stage5Count > 0
    ? `\n│\n├── [−${stage5Count}] Direction / Shortlist / Other (Left: ${leftAfterStage4 - stage5Count})\n│   ${directionCount > 0 ? `├── Direction Conviction: ${directionCount}\n│   ` : ''}${shortlistCount > 0 ? `├── Shortlist Cap: ${shortlistCount}\n│   ` : ''}${unmeasuredCount > 0 ? `├── Direction Unmeasured: ${unmeasuredCount}\n│   ` : ''}${otherCount > 0 ? `└── Other: ${otherCount}` : ''}`
    : '';

  const asciiTree = `Universe (${scanned})
│
├── [−${stage1Count}] Data & Filters (Left: ${leftAfterStage1}) · ${stages[0].pctOfTotal}% ${stages[0].isBottleneck ? '<-- [PRIMARY BOTTLENECK]' : ''}
│   ├── Price Out of Range (min/max): ${stages[0].subRules[0].count}
│   ├── Market Cap Out of Range: ${stages[0].subRules[1].count}
│   └── Missing Quotes / Bars: ${stages[0].subRules[2].count}
│
├── [−${stage2Count}] Pre-Screen Setup Score (Left: ${leftAfterStage2}) · ${stages[1].pctOfTotal}% ${stages[1].isBottleneck ? '<-- [PRIMARY BOTTLENECK]' : ''}
│   ├── Trend Rule Failed (EMA slope / ADX / RS): ${stages[1].subRules[0].count}
│   ├── Trigger Momentum Failed (RSI / MACD): ${stages[1].subRules[1].count}
│   ├── Pullback Broken / Too Deep (>2.5 ATR): ${stages[1].subRules[2].count}
│   ├── Event Risk (Earnings Proximity): ${stages[1].subRules[3].count}
│   └── Regime Headwind Gate: ${stages[1].subRules[4].count}
│
├── [−${stage3Count}] Option Chain Window (Left: ${leftAfterStage3}) · ${stages[2].pctOfTotal}% ${stages[2].isBottleneck ? '<-- [PRIMARY BOTTLENECK]' : ''}
│   ├── No Expiry in Target DTE Band: ${stages[2].subRules[0].count}
│   └── Empty Strike Matrix: ${stages[2].subRules[1].count}
│
├── [−${stage4Count}] Contract Scoring & Hard Rules (Left: ${leftAfterStage4}) · ${stages[3].pctOfTotal}% ${stages[3].isBottleneck ? '<-- [PRIMARY BOTTLENECK]' : ''}
│   ├── Spread Too Wide (ask-bid / mid > 15%): ${stages[3].subRules[0].count}
│   ├── Low Liquidity (OI < 500 or Volume < 50): ${stages[3].subRules[1].count}
│   ├── Delta Outside Range (< 0.30 or > 0.70): ${stages[3].subRules[2].count}
│   └── IV Elevated / IV Rank Ceiling: ${stages[3].subRules[3].count}${stage5Line}
│
└── Final Candidates: ${candidatesCount} Survivor${candidatesCount !== 1 ? 's' : ''}`;

  // Symbol lookup function
  function lookupSymbol(query: string): SymbolDiagnosticResult | null {
    if (!query) return null;
    const q = query.trim().toUpperCase();

    if (survivorSymbols.map((s) => s.toUpperCase()).includes(q)) {
      return {
        symbol: q,
        status: 'SURVIVOR',
        stageName: 'Passed All Gates',
        primaryReason: 'Qualified as a ranked candidate',
        detailedReason: 'Symbol passed stock scoring, option chain expiry resolution, and all hard contract gating rules.',
      };
    }

    const item = symbolMap.get(q);
    if (!item) return null;

    const r = item.reason.toLowerCase();
    let stageName = 'Other';
    let primaryReason = item.reason;

    if (r.includes('price filter') || r.includes('cap filter') || r.includes('no market data')) {
      stageName = 'Data & Universe Filters';
    } else if (item.reason.startsWith('Pre-screen:')) {
      stageName = 'Pre-Screen Setup Score';
      primaryReason = 'Setup score below qualification threshold';
    } else if (r === 'no option chain' || r.includes('no chain')) {
      stageName = 'Option Chain Window';
      primaryReason = 'No option expiration available in specified DTE window';
    } else if (r.includes('contracts rejected')) {
      stageName = 'Option Contract Rules';
      primaryReason = 'All options in chain failed liquidity, spread, delta, or IV gates';
    } else if (r.startsWith('direction_conviction')) {
      stageName = 'Direction Conviction';
      primaryReason = 'Trend strength below minimum conviction floor';
    } else if (r.includes('shortlist') || r.includes('over cap')) {
      stageName = 'Shortlist Allocation';
      primaryReason = 'Candidate survived all gates but was trimmed by shortlist ranking cap';
    }

    return {
      symbol: q,
      status: 'REJECTED',
      stageName,
      primaryReason,
      detailedReason: item.reason,
      breakdown: item.breakdown,
    };
  }

  return {
    scanned,
    candidatesCount,
    totalDropped,
    primaryBottleneck: {
      stageId: bottleneck.id,
      stageTitle: bottleneck.title,
      droppedCount: bottleneck.droppedCount,
      pctOfTotal: bottleneck.pctOfTotal,
      insight,
      suggestedAction,
    },
    stages,
    asciiTree,
    lookupSymbol,
  };
}
