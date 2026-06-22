// Per-horizon IV rank thresholds — mirrors scoring_rules.yaml horizons[N].vol section.
// iv_rank_pass_max and iv_rank_caution_max MUST stay in sync with the YAML.
// To change these thresholds, update the YAML first, then update values here.
// Intraday vol gate is disabled (null) — options screener uses its own IV logic for intraday.
export const IV_PASS_MAX: Record<string, number | null> = {
  Intraday: null,
  Swing:    34,
  Position: 44,
};

export const IV_CAUTION_MAX: Record<string, number | null> = {
  Intraday: null,
  Swing:    55,
  Position: 65,
};
