import { armBookingFieldsFrom, classifyFireFailure, type ArmBookingInputs } from '@/lib/armBookingFields';
import type { ExitPlan, MaxLossOverride, TargetLevel } from '@/types/domain';

const PLAN = { method: 'arithmetic', targets: [] } as unknown as ExitPlan;
const OVERRIDE = { maxLoss: 500 } as unknown as MaxLossOverride;
const TARGETS = [{ id: 'tp1', stockPrice: 200, targetPrice: 200 }] as unknown as TargetLevel[];

const full = (over: Partial<ArmBookingInputs> = {}): ArmBookingInputs => ({
  stop: 179.64,
  stopIsUserSet: true,
  scanStockPrice: 185.2,
  structuralStop: 178.1,
  exitPlan: PLAN,
  targets: TARGETS,
  dteTotal: 24,
  premiumStopDollar: 1.5,
  maxLossOverride: OVERRIDE,
  tradeCardSnapshot: { strike: 190 },
  ...over,
});

describe('armBookingFieldsFrom — O4 step 6 §2', () => {
  it('1. maps all ten keys, snake_case, values verbatim', () => {
    expect(armBookingFieldsFrom(full())).toEqual({
      stop: 179.64,
      stop_is_user_set: true,
      scan_stock_price: 185.2,
      structural_stop: 178.1,
      exit_plan: PLAN,
      targets: TARGETS,
      dte_total: 24,
      premium_stop_dollar: 1.5,
      max_loss_override: OVERRIDE,
      trade_card_snapshot: { strike: 190 },
    });
  });

  it('every key is present even when every input is absent', () => {
    const out = armBookingFieldsFrom({
      stop: undefined, stopIsUserSet: false, scanStockPrice: undefined, structuralStop: undefined,
      exitPlan: undefined, targets: undefined, dteTotal: undefined, premiumStopDollar: undefined,
      maxLossOverride: undefined, tradeCardSnapshot: undefined,
    });
    expect(Object.keys(out).sort()).toEqual([
      'dte_total', 'exit_plan', 'max_loss_override', 'premium_stop_dollar', 'scan_stock_price',
      'stop', 'stop_is_user_set', 'structural_stop', 'targets', 'trade_card_snapshot',
    ]);
    expect(out.exit_plan).toBeNull();
    expect(out.max_loss_override).toBeNull();
    expect(out.trade_card_snapshot).toBeNull();
  });

  // The arm endpoint bounds each of these gt=0: a 0 would 422 the whole arm.
  it.each(['stop', 'scanStockPrice', 'structuralStop', 'premiumStopDollar'] as const)(
    '2. %s sends null, never 0 or a negative, for an absent or non-positive value',
    (key) => {
      const wire = {
        stop: 'stop', scanStockPrice: 'scan_stock_price',
        structuralStop: 'structural_stop', premiumStopDollar: 'premium_stop_dollar',
      }[key] as 'stop' | 'scan_stock_price' | 'structural_stop' | 'premium_stop_dollar';
      for (const v of [0, -1, NaN, Infinity, undefined, null]) {
        expect(armBookingFieldsFrom(full({ [key]: v }))[wire]).toBeNull();
      }
    },
  );

  it('3. targets: null/undefined -> [] (the backend field is a list, not Optional)', () => {
    expect(armBookingFieldsFrom(full({ targets: null })).targets).toEqual([]);
    expect(armBookingFieldsFrom(full({ targets: undefined })).targets).toEqual([]);
  });

  it('4. dte_total: a non-negative integer or null — never invented', () => {
    const dte = (v: number | null | undefined) => armBookingFieldsFrom(full({ dteTotal: v })).dte_total;
    expect(dte(24)).toBe(24);
    expect(dte(0)).toBe(0);
    expect(dte(-1)).toBeNull();
    expect(dte(24.5)).toBeNull();
    expect(dte(undefined)).toBeNull();
    expect(dte(null)).toBeNull();
  });

  it('5. stop_is_user_set is a real boolean, never null', () => {
    expect(armBookingFieldsFrom(full({ stopIsUserSet: true })).stop_is_user_set).toBe(true);
    expect(armBookingFieldsFrom(full({ stopIsUserSet: false })).stop_is_user_set).toBe(false);
  });
});

describe('classifyFireFailure — O4 step 6 §5.3', () => {
  const api = (status: number, detail: string) => new Error(`API /auto-trade/fire → ${status}: ${detail}`);

  it('6a. a 400 refused before the broker call is "refused"', () => {
    expect(classifyFireFailure(api(400, 'AutoTrader not armed — cannot fire'))).toBe('refused');
    expect(classifyFireFailure(api(400, 'Order not submitted: no conid'))).toBe('refused');
    expect(classifyFireFailure(api(400, 'Exposure cap breach: [...]'))).toBe('refused');
  });

  it('6b. a 400 "Order failed:" — the broker call was made — is "unknown"', () => {
    expect(classifyFireFailure(api(400, 'Order failed: read timeout'))).toBe('unknown');
  });

  it('6c. a 5xx, a transport failure or a non-Error is "unknown"', () => {
    expect(classifyFireFailure(api(500, 'Internal Server Error'))).toBe('unknown');
    expect(classifyFireFailure(api(502, ''))).toBe('unknown');
    expect(classifyFireFailure(new TypeError('Failed to fetch'))).toBe('unknown');
    expect(classifyFireFailure(new Error('The operation was aborted'))).toBe('unknown');
    expect(classifyFireFailure('boom')).toBe('unknown');
    expect(classifyFireFailure(undefined)).toBe('unknown');
  });
});
