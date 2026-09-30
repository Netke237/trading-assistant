// Test fixtures ONLY — DOCC-4 health reports in the shape
// backend/app/services/config_health.py report() returns. No production module
// may import this file. It sits outside __tests__ so jest does not collect it.
import type { ConfigHealthReport } from '@/lib/configHealth';

/** Verbatim CHECK_ORDER (config_health.py). */
export const SHIPPED_CHECKED = [
  'scoring_rules.yaml parses',
  'money blocks: presence, spelling, enabled',
  'regime_sizing values',
  'regime blocks (intraday, swing, position)',
  'direction_conviction: position and values',
  'top-level families',
  'horizons tree: unknown keys',
  'risk_rules.yaml parses',
  'contract_rules.yaml parses',
  'running config vs disk',
];

/** Verbatim NOT_CHECKED (config_health.py). */
export const SHIPPED_NOT_CHECKED = [
  'money blocks other than regime_sizing: values',
  'required non-money sections and keys (horizons.<h>.*, stock_score_thresholds, '
    + 'confidence_backtest, risk_rules sections)',
  'risk_rules.yaml and contract_rules.yaml contents',
  'single worker assumed; only WEB_CONCURRENCY is detected',
  'copies the frontend fetched at page load (event and IV thresholds)',
];

export const CLEAN_REPORT: ConfigHealthReport = {
  ok: true, checked: [...SHIPPED_CHECKED], not_checked: [...SHIPPED_NOT_CHECKED], pid: 4242,
  errors: [], warnings: [], stale: [],
};

export const ERROR_REPORT: ConfigHealthReport = {
  ...CLEAN_REPORT, ok: false,
  errors: [{
    file: 'scoring_rules.yaml', path: 'regime_sizing.full_conviction_pct',
    message: 'must be a number between 0 and 100',
    blocks: 'the stock scan and every auto-trade fire',
  }],
};

export const STALE_REPORT: ConfigHealthReport = {
  ...CLEAN_REPORT, ok: false,
  stale: [{
    file: 'risk_rules.yaml', path: 'max_loss_per_trade',
    message: 'disk differs from running config -- restart',
  }],
};

export const WARNING_REPORT: ConfigHealthReport = {
  ...CLEAN_REPORT, ok: false,
  warnings: [{ file: 'scoring_rules.yaml', path: 'horizons.Swing.evnt', message: 'unknown key, never read' }],
};

/** The report() crash shape: nothing checked, one error with empty file/path/blocks. */
export const CRASH_REPORT: ConfigHealthReport = {
  ok: false, checked: [], not_checked: [...SHIPPED_NOT_CHECKED], pid: 4242,
  errors: [{ file: '', path: '', blocks: '', message: "health check crashed: RuntimeError('boom')" }],
  warnings: [], stale: [],
};
