import { parsePipelineDiagnostics } from '@/lib/parsePipelineDiagnostics';
import type { OptionsPipeline, RejectedEntry } from '@/lib/scanStore';

describe('Options Contract Floor Override Diagnostics (AC 1 & AC 2, #389)', () => {
  const pipeline: OptionsPipeline = {
    scanned: 1,
    failed_data: 0,
    failed_pre_screen: 0,
    failed_direction_unmeasured: 0,
    no_chain: 0,
    failed_score: 0,
    failed_contracts: 1,
    failed_direction: 0,
    failed_shortlist: 0,
    other_rejected: 0,
    direction_min_trend: 40,
    candidates: 0,
  };

  const rejected: RejectedEntry[] = [
    { symbol: 'FAILSTOCK', reason: 'contracts rejected: stock_score_below_threshold(5)' },
  ];

  it('AC 1: displays override parenthetical (< 30) when contract_min_stock_score override is set to 30', () => {
    const report = parsePipelineDiagnostics(pipeline, rejected, [], {
      contractRules: { min_stock_score: 30 },
    });

    const stage = report.stages.find((s) => s.id === 'contract-rules');
    expect(stage).toBeDefined();
    const subRule = stage?.subRules.find((sub) => sub.id === 'min-stock-score');
    expect(subRule).toBeDefined();
    expect(subRule?.label).toBe('Stock Score Below Contract Minimum (< 30)');
    expect(subRule?.ruleExplanation).toContain('Threshold: the Step-3 override this scan recorded.');
    expect(subRule?.symbols).toEqual(['FAILSTOCK']);
  });

  it('AC 2: displays plain label without parenthetical when no override is set and refers to contract_rules.yaml in tooltip', () => {
    const report = parsePipelineDiagnostics(pipeline, rejected, [], {
      contractRules: {}, // Empty overrides: default YAML applies
    });

    const stage = report.stages.find((s) => s.id === 'contract-rules');
    expect(stage).toBeDefined();
    const subRule = stage?.subRules.find((sub) => sub.id === 'min-stock-score');
    expect(subRule).toBeDefined();
    // No parenthetical override
    expect(subRule?.label).toBe('Stock Score Below Contract Minimum');
    // Explanation explicitly names contract_rules.yaml min_stock_score
    expect(subRule?.ruleExplanation).toContain('contract_rules.yaml `min_stock_score`');
    expect(subRule?.symbols).toEqual(['FAILSTOCK']);
  });
});
