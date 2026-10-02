import { parsePipelineDiagnostics } from '../parsePipelineDiagnostics';
import type { OptionsPipeline, RejectedEntry } from '../scanStore';

describe('parsePipelineDiagnostics engine', () => {
  const mockPipeline: OptionsPipeline = {
    scanned: 500,
    failed_data: 20,
    failed_pre_screen: 250,
    no_chain: 150,
    failed_score: 50,
    failed_contracts: 28,
    candidates: 2,
  };

  const mockRejected: RejectedEntry[] = [
    { symbol: 'PENNY', reason: 'price filter ($2.10 < $15.00 min)' },
    { symbol: 'TINY', reason: 'cap filter ($1.2B < $5.0B min)' },
    { symbol: 'NODATA', reason: 'no market data' },
    {
      symbol: 'BADTREND',
      reason: 'Pre-screen: score 28 rejected',
      breakdown: { trend: 20, pullback: 60, trigger: 70, event: 80, regime: 90 },
    },
    {
      symbol: 'BADEVENT',
      reason: 'Pre-screen: score 30 rejected',
      breakdown: { trend: 70, pullback: 60, trigger: 70, event: 15, regime: 90 },
    },
    { symbol: 'NOOPT', reason: 'no option chain' },
    { symbol: 'NOSTRIKE', reason: 'empty strike matrix' },
    {
      symbol: 'NVDA',
      reason: 'contracts rejected: spread_too_wide(14), volume_too_low(8)',
    },
    {
      symbol: 'TSLA',
      reason: 'contracts rejected: delta_too_low(6)',
    },
    {
      symbol: 'HIGHIV',
      reason: 'contracts rejected: iv_too_high(5)',
    },
    {
      symbol: 'LOWCONV',
      reason: 'direction_conviction below threshold',
    },
    {
      symbol: 'OVERCAP',
      reason: 'shortlist cap reached',
    },
  ];

  it('correctly aggregates stage counts and calculates percentage shares', () => {
    const report = parsePipelineDiagnostics(mockPipeline, mockRejected, ['AAPL', 'MSFT']);

    expect(report.scanned).toBe(500);
    expect(report.candidatesCount).toBe(2);
    expect(report.totalDropped).toBe(498);

    // Stage 1: Data & Universe Filters
    const stage1 = report.stages.find((s) => s.id === 'data-filters');
    expect(stage1).toBeDefined();
    expect(stage1?.droppedCount).toBe(20);
    expect(stage1?.allSymbols).toContain('PENNY');
    expect(stage1?.allSymbols).toContain('TINY');
    expect(stage1?.allSymbols).toContain('NODATA');

    // Stage 2: Pre-Screen Setup Score
    const stage2 = report.stages.find((s) => s.id === 'pre-screen');
    expect(stage2).toBeDefined();
    expect(stage2?.droppedCount).toBe(250);
    expect(stage2?.allSymbols).toContain('BADTREND');
    expect(stage2?.allSymbols).toContain('BADEVENT');

    // Stage 3: Option Chain Window
    const stage3 = report.stages.find((s) => s.id === 'chain-window');
    expect(stage3).toBeDefined();
    expect(stage3?.droppedCount).toBe(150);
    expect(stage3?.allSymbols).toContain('NOOPT');
    expect(stage3?.allSymbols).toContain('NOSTRIKE');

    // Stage 4: Contract Rules
    const stage4 = report.stages.find((s) => s.id === 'contract-rules');
    expect(stage4).toBeDefined();
    expect(stage4?.allSymbols).toContain('NVDA');
    expect(stage4?.allSymbols).toContain('TSLA');
    expect(stage4?.allSymbols).toContain('HIGHIV');
  });

  it('identifies the primary bottleneck stage correctly', () => {
    const report = parsePipelineDiagnostics(mockPipeline, mockRejected, ['AAPL', 'MSFT']);
    // Pre-screen dropped 250 out of 500, which is the largest drop
    expect(report.primaryBottleneck.stageId).toBe('pre-screen');
    expect(report.primaryBottleneck.droppedCount).toBe(250);
    expect(report.primaryBottleneck.insight).toContain('setup score gate rejected');
  });

  it('identifies chain-window bottleneck when chain drops the most', () => {
    const chainHeavyPipeline: OptionsPipeline = {
      scanned: 300,
      failed_data: 10,
      failed_pre_screen: 20,
      no_chain: 200,
      failed_score: 10,
      failed_contracts: 10,
      candidates: 50,
    };
    const report = parsePipelineDiagnostics(chainHeavyPipeline, [], ['AAPL']);
    expect(report.primaryBottleneck.stageId).toBe('chain-window');
    expect(report.primaryBottleneck.droppedCount).toBe(200);
    expect(report.primaryBottleneck.insight).toContain('DTE holding horizon eliminated');
    expect(report.primaryBottleneck.suggestedAction).toContain('Widen DTE window');
  });

  it('identifies contract-rules bottleneck when contract scoring drops the most', () => {
    const contractHeavyPipeline: OptionsPipeline = {
      scanned: 200,
      failed_data: 5,
      failed_pre_screen: 10,
      no_chain: 15,
      failed_score: 90,
      failed_contracts: 50,
      candidates: 30,
    };
    const report = parsePipelineDiagnostics(contractHeavyPipeline, [], ['AAPL']);
    expect(report.primaryBottleneck.stageId).toBe('contract-rules');
    expect(report.primaryBottleneck.droppedCount).toBe(140);
    expect(report.primaryBottleneck.insight).toContain('Contract liquidity and spread rules');
  });

  it('identifies data-filters bottleneck when data filters drop the most', () => {
    const dataHeavyPipeline: OptionsPipeline = {
      scanned: 100,
      failed_data: 80,
      failed_pre_screen: 5,
      no_chain: 5,
      failed_score: 2,
      failed_contracts: 1,
      candidates: 7,
    };
    const report = parsePipelineDiagnostics(dataHeavyPipeline, [], ['AAPL']);
    expect(report.primaryBottleneck.stageId).toBe('data-filters');
    expect(report.primaryBottleneck.droppedCount).toBe(80);
    expect(report.primaryBottleneck.insight).toContain('Universe and data filters eliminated');
  });

  it('performs accurate symbol diagnosis lookup for survivor and rejected tickers', () => {
    const report = parsePipelineDiagnostics(mockPipeline, mockRejected, ['AAPL', 'MSFT']);

    // Survivor lookup
    const survivor = report.lookupSymbol('AAPL');
    expect(survivor).not.toBeNull();
    expect(survivor?.status).toBe('SURVIVOR');
    expect(survivor?.stageName).toBe('Passed All Gates');

    // Case insensitivity
    const msft = report.lookupSymbol('msft');
    expect(msft?.status).toBe('SURVIVOR');

    // Rejected lookup with breakdown
    const badTrend = report.lookupSymbol('BADTREND');
    expect(badTrend).not.toBeNull();
    expect(badTrend?.status).toBe('REJECTED');
    expect(badTrend?.stageName).toBe('Pre-Screen Setup Score');
    expect(badTrend?.breakdown?.trend).toBe(20);

    // Contract rejected lookup
    const nvda = report.lookupSymbol('NVDA');
    expect(nvda).not.toBeNull();
    expect(nvda?.status).toBe('REJECTED');
    expect(nvda?.stageName).toBe('Option Contract Rules');
    expect(nvda?.detailedReason).toContain('spread_too_wide(14)');

    // Direction conviction lookup
    const lowConv = report.lookupSymbol('LOWCONV');
    expect(lowConv).not.toBeNull();
    expect(lowConv?.status).toBe('REJECTED');
    expect(lowConv?.stageName).toBe('Direction Conviction');

    // Shortlist lookup
    const overCap = report.lookupSymbol('OVERCAP');
    expect(overCap).not.toBeNull();
    expect(overCap?.status).toBe('REJECTED');
    expect(overCap?.stageName).toBe('Shortlist Allocation');

    // Non-existent symbol
    const unknown = report.lookupSymbol('UNKNOWN');
    expect(unknown).toBeNull();

    // Empty or whitespace query
    expect(report.lookupSymbol('')).toBeNull();
    expect(report.lookupSymbol('   ')).toBeNull();
  });

  it('generates a clean ASCII tree with primary bottleneck indicator', () => {
    const report = parsePipelineDiagnostics(mockPipeline, mockRejected, ['AAPL', 'MSFT']);
    expect(report.asciiTree).toContain('Universe (500)');
    expect(report.asciiTree).toContain('Pre-Screen Setup Score');
    expect(report.asciiTree).toContain('<-- [PRIMARY BOTTLENECK]');
    expect(report.asciiTree).toContain('Final Candidates: 2 Survivors');
  });

  it('handles empty / zero-data gracefully without NaN', () => {
    const report = parsePipelineDiagnostics(undefined, [], []);
    expect(report.scanned).toBe(0);
    expect(report.candidatesCount).toBe(0);
    expect(report.totalDropped).toBe(0);
    for (const stage of report.stages) {
      expect(Number.isNaN(stage.pctOfTotal)).toBe(false);
      for (const sub of stage.subRules) {
        expect(Number.isNaN(sub.pctOfStage)).toBe(false);
        expect(Number.isNaN(sub.pctOfTotal)).toBe(false);
      }
    }
  });

  it('dynamically computes sub-rule percentages when symbols are present vs fallback ratios when empty', () => {
    // 1. With symbols present
    const reportWithSymbols = parsePipelineDiagnostics(mockPipeline, mockRejected, ['AAPL', 'MSFT']);
    const stage1 = reportWithSymbols.stages.find((s) => s.id === 'data-filters')!;
    const priceSub = stage1.subRules.find((r) => r.id === 'price-filter')!;
    // priceRejects has 1 symbol ('PENNY'), stage1 droppedCount is 20, scanned is 500
    expect(priceSub.count).toBe(1);
    expect(priceSub.pctOfStage).toBe(Math.round((1 / 20) * 100)); // 5%
    expect(priceSub.pctOfTotal).toBe(Math.round((1 / 500) * 100)); // 0%

    // 2. Without symbols present (fallback to estimated ratios)
    const reportWithoutSymbols = parsePipelineDiagnostics(mockPipeline, [], ['AAPL', 'MSFT']);
    const fallbackStage1 = reportWithoutSymbols.stages.find((s) => s.id === 'data-filters')!;
    const fallbackPriceSub = fallbackStage1.subRules.find((r) => r.id === 'price-filter')!;
    // Fallback ratio for price filter is 0.6 of stage1Count (20 * 0.6 = 12)
    expect(fallbackPriceSub.count).toBe(12);
    expect(fallbackPriceSub.pctOfStage).toBe(Math.round((12 / 20) * 100)); // 60%
    expect(fallbackPriceSub.pctOfTotal).toBe(Math.round((12 / 500) * 100)); // 2%
  });
});
