/**
 * STOP-SEMANTICS-2026-10-02 -- the Portfolio banner's rendering of a PATCH 422
 * detail: ` | `-joined segments, each mapped on its own (plan §3.1).
 */
import { REJECTION_LABELS, isPartialSave, rejectionMessage } from '@/lib/portfolioRejection';

const PREMIUM = REJECTION_LABELS.premium_stop_below_one_cent!;

describe('rejectionMessage', () => {
  it('maps a risk-code qty error AND the premium code', () => {
    expect(rejectionMessage('single_trade_exposure_too_high | premium_stop_below_one_cent')).toBe(
      `${REJECTION_LABELS.single_trade_exposure_too_high} ${PREMIUM}`);
  });

  it.each([
    'qty must be an integer of at least 1.',
    'portfolioValue is required to increase qty.',
    'size_reduced_to_fit_exposure_limit: the position is already at or over its exposure cap (5 held; the cap allows 3). Quantity not increased.',
  ])('shows a free-text qty error verbatim beside the premium label: %s', (qtyError) => {
    expect(rejectionMessage(`${qtyError} | premium_stop_below_one_cent`)).toBe(`${qtyError} ${PREMIUM}`);
  });

  it('maps qty_saved_as_<N> by exact prefix and digits only (N2)', () => {
    expect(rejectionMessage('premium_stop_below_one_cent | qty_saved_as_3')).toBe(
      `${PREMIUM} Quantity saved as 3 (reduced to fit exposure).`);
    expect(rejectionMessage('qty_saved_as_x')).toBe('qty_saved_as_x');
    expect(rejectionMessage('xqty_saved_as_3')).toBe('xqty_saved_as_3');
  });

  it('a single-segment detail renders exactly as before', () => {
    expect(rejectionMessage('single_trade_exposure_too_high total_exposure_limit_reached')).toBe(
      `${REJECTION_LABELS.single_trade_exposure_too_high} ${REJECTION_LABELS.total_exposure_limit_reached}`);
    expect(rejectionMessage('qty must be an integer of at least 1.')).toBe('qty must be an integer of at least 1.');
  });
});

describe('isPartialSave', () => {
  it('only for the premium code and/or a saved trimmed qty', () => {
    expect(isPartialSave('premium_stop_below_one_cent')).toBe(true);
    expect(isPartialSave('premium_stop_below_one_cent | qty_saved_as_3')).toBe(true);
    expect(isPartialSave('single_trade_exposure_too_high | premium_stop_below_one_cent')).toBe(false);
    expect(isPartialSave('qty must be an integer of at least 1.')).toBe(false);
  });
});
