// Per-horizon IV rank thresholds mirroring scoring_rules.yaml.
// Used by Step 5 so row colouring matches what the backend actually enforces.
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
