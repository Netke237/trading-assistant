/*
 * Step 5's gate-summary copy: the missing-reading claim and the sentence
 * builders the page renders above its table. Pure (no React), and kept out of
 * page.tsx because a Next.js page file may only export the page and Next's own
 * config fields -- `next build` rejects any other named export. The page and
 * its tests import from here.
 */
import type { Status } from '@/lib/status';
import { formatIv, type IvBasis, type ResolvedIv } from '@/lib/ivBasis';
import type { HorizonEventThresholds, ThresholdHorizon } from '@/lib/eventThresholdsStore';
import type { HorizonIvThresholds } from '@/lib/ivThresholdsStore';
import { gateDriverPhrase, type GateDrivers } from '@/lib/statusTooltips';

/* ── THE MISSING-READING CLAIM ──────────────────────────────────
 * THE MEANING IS RENDERED AS DATA. The four fields below go into the DOM as
 * `data-claim-*` attributes on the element that carries the sentence, and the
 * sentence is that same claim run through `missingReadingClause`. The tests
 * read the attributes; the English is a rendering of them, not the carrier.
 *
 * WHY, AND THE EVIDENCE IS TEN ROUNDS DEEP. Four consecutive adversarial
 * rounds tried to prove the PROSE correct and each closed one hole while
 * opening another: regex whitelists, then "positive" regex rules, then a
 * data-driven clause compared with `toContain`, then that plus a three-token
 * "no verdict word outside the clause" rule. Round 4 measured that last rule
 * ADMITTING false copy ("safe to trade as if they were clean", green) and
 * REJECTING true copy (11 red on a statement true of the page) at the same
 * time. Each of these shipped a full green suite:
 *   "graded PASS ... never CAUTION"      the semantic INVERSE of the gate
 *   "on the event side"                  the wrong side entirely
 *   "so it can be easier still"          a worst-of that gets easier
 *   "In the worst case, open the column" the reconciliation sentence deleted,
 *                                        with one list word left behind
 * The rules were not the defect; grading English with regexes was.
 *
 * WHAT REPLACES THEM. Every field below is answerable to something the page
 * RENDERS, not to a constant a human retyped in the test file:
 *   side        → each row publishes `data-side-volatility` and
 *                 `data-side-event`; exactly one of them equals `asserted` on
 *                 the row the clause describes, and it must be the one named.
 *   asserted    → that same attribute, plus the head's count for the verdict.
 *   denied      → the OTHER branch of the same ternary, observed by rendering
 *                 the same row on a horizon where volatility does not gate.
 *   combination → a row whose two sides genuinely disagree: `worse` and
 *                 `better` predict different gates, and only one is rendered.
 * A reworded clause can therefore say the same thing differently, but it
 * cannot say something different -- to do that you must change the claim, and
 * every field of the claim is pinned to behaviour. The skeleton itself is
 * pinned by one exact-string test, which is the only place a literal belongs.
 */
export type MissingReadingClaim = {
  /** Which side of the gate graded the row. */
  side: 'volatility' | 'event';
  /** The sub-verdict that side gives an unreadable row. */
  asserted: Status;
  /** The sub-verdict it explicitly does NOT give. */
  denied: Status;
  /** How the two sides combine. `worstStatus` is 'worse'. */
  combination: 'worse' | 'better';
};

const SIDE_LABEL = {
  volatility: 'the volatility side',
  event:      'the event side',
} as const;

const COMBINATION_LABEL = {
  worse:  { of: 'worse',  travel: 'lower'  },
  better: { of: 'better', travel: 'higher' },
} as const;

/* ── THE BANNER'S CLOSED VOCABULARY ───────────────────────────────
 * ROUND 1 OF THE STRUCTURAL LOOP FOUND THE CLAIM WAS THE ONLY PART TREATED
 * THIS WAY, and that the others were graded by punctuation. Measured: with the
 * causes sentence held to "one sentence" (`/^[^.]*\.$/`), appending
 * "; these rows are safe to trade as if they were clean." shipped 51/51 GREEN
 * -- a semicolon buys any lie -- while appending a TRUE sentence with a full
 * stop went red. That is round 4's finding reproduced verbatim against the
 * replacement: false copy admitted and true copy rejected, at one edit site.
 *
 * So every cause the banner can name is a KEY, and its words live in one
 * table that a single test pins by equality. A new phrase has to be a new
 * entry here, and free text appended to an existing one fails that pin. The
 * counts beside them come from the rows; the sentence is a rendering of both.
 */
export const CAUSE_LABEL = {
  ivRank: 'on IV rank above its threshold',
  ivAbs:  'on IV above its threshold',
  event:  "on an event inside this horizon's window",
} as const;
export type CauseKey = keyof typeof CAUSE_LABEL;

export type GateCounts = { total: number; pass: number; caution: number; reject: number };
export type GateCause  = { n: number; key: CauseKey };

/** One band per IV basis on screen, as the threshold sentence states them. */
export type IvBand = { basis: IvBasis; passMax: number; cautionMax: number | null };

/* THE NUMBERS ARE THE CLAIM HERE, and round 2 measured them ungraded: shifting
 * the PASS max by 20 in this sentence -- so the page said "IV rank <= 54 -> PASS"
 * while rejecting at 34 -- shipped 1740/1740, because the pin was a regex with
 * `\d+` holes in it. Same defect the four claim fields were rebuilt to remove,
 * left standing on the numbers beside them. Then: a builder over published
 * bands, pinned by equality against ITSELF -- round 7 measured swapping the two
 * bands inside this function shipping green, because gateSummary.test.tsx's pin
 * rebuilds its expectation with this same builder. What catches a change to the
 * numbers or their order is __tests__/literalPins.test.tsx: literal strings,
 * for the builder and for the rendered page. */
export function ivThresholdSentence(bands: IvBand[]): string {
  return bands
    .map((b) => `${b.basis === 'rank' ? 'IV rank' : 'IV'} ${ivInterval(b.passMax, b.cautionMax)}.`)
    .join(' ');
}

function ivInterval(passMax: number, cautionMax: number | null, unit = ''): string {
  if (cautionMax !== null && passMax >= cautionMax) {
    return `≤ ${passMax}${unit} → PASS; > ${passMax}${unit} → REJECT; CAUTION: no reachable interval`;
  }
  return cautionMax === null
    ? `≤ ${passMax}${unit} → PASS; above → REJECT`
    : `≤ ${passMax}${unit} → PASS; ≤ ${cautionMax}${unit} → CAUTION; above → REJECT`;
}

function eventInterval(w: HorizonEventThresholds): string {
  return w.reject_days >= w.caution_days
    ? `< ${w.reject_days}d → REJECT; ≥ ${w.reject_days}d → PASS; CAUTION: no reachable interval`
    : `< ${w.reject_days}d → REJECT; < ${w.caution_days}d → CAUTION; else → PASS`;
}

/** Preserve the classifier's observation; retain the usual decimal style when exact. */
export function formatGateIv(iv: ResolvedIv, symbol?: string): ReturnType<typeof formatIv> {
  const shown = formatIv(iv, symbol);
  if (iv.value === null) return shown;
  const text = iv.basis === 'absolute'
    ? `${Number.isInteger(iv.value) ? iv.value.toFixed(1) : String(iv.value)}%`
    : String(iv.value);
  return { ...shown, text, title: shown.title.replace(shown.text, text) };
}

/* THE BOUNDARY IS PART OF THE CLAIM, and this sentence got it wrong while
 * every other statement of the same window got it right. It read "Earnings
 * within {caution} days -> CAUTION; within {reject} days -> REJECT", which
 * reads INCLUSIVE -- so the page announced an earnings date landing exactly on
 * day 21 as a REJECT. The ternary forty lines below grades it CAUTION (strict
 * `<`), the row tooltip one pixel away words it `reject <21d / caution <45d`,
 * and backend stock_scorer.py's _rule_event applies `< reject_days` too. Three
 * agreeing consumers and one sentence contradicting all of them, with no test
 * on the event boundary at all -- the IV boundary has a table of its own.
 * Stated now as the inequality the stack actually applies, the way the IV
 * sentence above states `<=` and the tooltip states `<`. */
export function eventWindowSentence(w: HorizonEventThresholds): string {
  return `Earnings ${eventInterval(w)}.`;
}

/** Whether both threshold records are in hand. `ready` does not require the
 *  stores' status to be 'ready': a re-fetch in flight keeps the last good
 *  record on screen. Published on the page root as `data-avail`. */
export type ThresholdsAvail = 'ready' | 'loading' | 'failed';

/** The header part (and the GATE tooltip) shown in place of every threshold
 *  sentence while no verdict can be computed. It quotes no number. */
export function thresholdsUnavailableSentence(avail: Exclude<ThresholdsAvail, 'ready'>, error: string | null): string {
  return avail === 'loading'
    ? 'Loading the volatility and event thresholds from scoring_rules.yaml\u2026'
    : `The volatility and event thresholds could not be loaded from scoring_rules.yaml (${error ?? 'unknown error'}). No IV or event verdict is shown.`;
}

/** The header part naming an active Settings override of the IV pass ceiling. */
export function ivOverrideSentence(value: number, yaml: number): string {
  return `IV pass ceiling is a session override from Settings (${value}), not scoring_rules.yaml's (${yaml}).`;
}

export function headSentence(c: GateCounts): string {
  return `${c.total} shown \u2014 ${c.pass} PASS, ${c.caution} CAUTION, ${c.reject} REJECT.`;
}

export function causesSentence(causes: GateCause[], overlap: boolean): string {
  // A row can be driven by its volatility AND an event, so these need not sum
  // to the non-PASS count. Said out loud, because on screen there was no cue at
  // all and "17 causes for 12 rows" reads as a bug.
  const cue = overlap ? ' (a row can have more than one)' : '';
  return `Driven by measured checks${cue}: ${causes.map((c) => `${c.n} ${CAUSE_LABEL[c.key]}`).join('; ')}.`;
}

/** The banner's second line, before it is words. `causes` and `missing` are
 *  independently optional: a scan can be entirely readable (causes, no claim),
 *  entirely unreadable with nothing else driving it (claim, no causes), or
 *  both. Each becomes its own `data-part` element, carrying the data it was
 *  rendered from, so the tests can pin every part by EQUALITY against that
 *  data rather than by a rule over its English. */
export type GateSummary = {
  counts: GateCounts;
  causes: { list: GateCause[]; overlap: boolean } | null;
  missing: { rows: number; claim: MissingReadingClaim } | null;
};

/* THE CLAIM IS A MODULE CONSTANT, and it is out here rather than inside the
 * memo on purpose. Round 2 of the structural loop measured why: with the claim
 * built inside the memo it could SEE `noReading`, and a claim that told the
 * truth at or below 25 rows and inverted above it shipped 67/67 green --
 * rendering all four of the failures listed above, in one sentence. Three
 * rounds had each moved that wall outward (n>=3, then >20, then >25) and each
 * time the next round found it one step further out.
 *
 * Out here the claim has nothing to be keyed ON: no row, no count, no scan.
 * The test imports this exact object and every render in the suite is checked
 * against it. BEING HONEST ABOUT THE RESIDUAL: TypeScript cannot stop someone
 * writing `noReading > N ? somethingElse : MISSING_READING_CLAIM` at the call
 * site, so this is not a proof. What closes it for the PRODUCT is the pair of
 * this constant and a fixture rendering more unreadable rows than the largest
 * universe can produce -- above that n there is no scan left to hide in. */
export const MISSING_READING_CLAIM: MissingReadingClaim = Object.freeze({
  //   side:     an unreadable row's verdict is set on the IV branch of the gate
  //             (`hasIv ? ... : gateDisabled ? 'PASS' : 'CAUTION'`); the event
  //             branch never sees `hasIv` at all.
  side:        'volatility',
  //   asserted/denied: the two arms of that one ternary. The clause renders
  //             only where the horizon DOES gate on volatility, so the live arm
  //             is CAUTION and PASS is the arm such a row cannot reach.
  asserted:    'CAUTION',
  denied:      'PASS',
  //   combination: the gate is worstStatus(iv, event) -- worse, never better.
  combination: 'worse',
});

export function missingReadingClause(n: number, claim: MissingReadingClaim): string {
  const { of, travel } = COMBINATION_LABEL[claim.combination];
  return (
    `${n} of them ${n === 1 ? 'has' : 'have'} no volatility reading at all — ` +
    `graded ${claim.asserted} on ${SIDE_LABEL[claim.side]} alone, never ${claim.denied} there. ` +
    `The gate verdict above is the ${of} of that and the event window, ` +
    `so it can be ${travel} still.`
  );
}

/* ── PURE EXPLANATION PRESENTATION MODELS (AC1 - AC4) ─────────────────────── */

export interface RulesStripData {
  horizon: ThresholdHorizon;
  provenance: 'Recorded scan event window' | 'Legacy scan: current configuration fallback' | 'Current backend configuration';
  rankInterval: string;
  absInterval: string;
  eventInterval: string;
  overrideNotice: string | null;
}

export function formatRulesStripData(args: {
  horizon: ThresholdHorizon;
  ivThresholds: HorizonIvThresholds | null;
  eventWindow: HorizonEventThresholds | null;
  scanEventWindow?: HorizonEventThresholds | null;
  hasScanResult: boolean;
  ivOverride?: { value: number; yaml: number } | null;
  basesPresent?: IvBasis[];
}): RulesStripData {
  const {
    horizon,
    ivThresholds,
    eventWindow,
    scanEventWindow,
    hasScanResult,
    ivOverride,
    basesPresent = [],
  } = args;

  const provenance = scanEventWindow
    ? 'Recorded scan event window'
    : hasScanResult
      ? 'Legacy scan: current configuration fallback'
      : 'Current backend configuration';

  // Rank interval
  let rankInterval = 'ungated';
  if (ivThresholds && ivThresholds.rank_pass_max !== null) {
    const passMax = ivThresholds.rank_pass_max;
    const cautionMax = ivThresholds.rank_caution_max;
    rankInterval = ivInterval(passMax, cautionMax);
  }

  // Absolute interval
  let absInterval = 'ungated';
  if (ivThresholds && ivThresholds.abs_pass_max !== null) {
    const passMax = ivThresholds.abs_pass_max;
    const cautionMax = ivThresholds.abs_caution_max;
    absInterval = ivInterval(passMax, cautionMax, '%');
  }

  // Event interval
  let eventInterval = 'No event window';
  if (eventWindow) {
    eventInterval = eventWindowSentence(eventWindow).slice(0, -1);
  }

  // Override notice
  let overrideNotice: string | null = null;
  if (ivOverride) {
    const notApplicable = basesPresent.length > 0 && !basesPresent.includes('absolute');
    overrideNotice = `Session override: IV pass ≤ ${ivOverride.value}% (YAML baseline: ${ivOverride.yaml}%)${notApplicable ? ' — not applicable to IV rank values displayed' : ''}`;
  }

  return {
    horizon,
    provenance,
    rankInterval,
    absInterval,
    eventInterval,
    overrideNotice,
  };
}

export function rowDecidingReason(
  gate: Status,
  drivers: GateDrivers,
  ivBasis: IvBasis,
  avail: ThresholdsAvail = 'ready',
): string {
  if (avail !== 'ready' || gate === 'PENDING' || gate === 'NO_DATA') return '—';
  if (gate === 'PASS') return 'No adverse driver';
  const ivNoun = ivBasis === 'rank' ? 'IV rank' : 'IV';
  if (drivers.iv && drivers.event) {
    const ivText = drivers.ivMissing ? 'No volatility reading' : ivNoun;
    return `${ivText} and event proximity`;
  }
  if (drivers.iv) {
    return drivers.ivMissing ? 'No volatility reading' : ivNoun;
  }
  if (drivers.event) {
    return 'Event proximity';
  }
  return 'No adverse driver';
}

export function rowCombinationPhrase(
  ivSt: Status,
  proxStatus: Status,
  gate: Status,
  drivers: GateDrivers,
  ivBasis: IvBasis,
  avail: ThresholdsAvail = 'ready',
): string {
  if (avail !== 'ready' || gate === 'PENDING' || gate === 'NO_DATA') {
    return `${ivSt} + ${proxStatus} → ${gate}`;
  }
  if (gate === 'PASS') {
    return `${ivSt} + ${proxStatus} → PASS`;
  }
  const ivNoun = ivBasis === 'rank' ? 'IV rank' : 'IV';
  const driverText = gateDriverPhrase(drivers, ivNoun);
  return `${ivSt} + ${proxStatus} → ${gate}, driven by ${driverText}`;
}

export interface RowExplanation {
  basisLabel: string;
  unit: string;
  decidingReason: string;
  combination: string;
  ivObserved: string;
  ivRuleExplanation: string;
  eventObserved: string;
  eventRuleExplanation: string;
  pctlFormatted: string;
}

export function formatRowExplanation(args: {
  iv: { basis: IvBasis; value: number | null };
  hasIv: boolean;
  ivSt: Status;
  proxStatus: Status;
  gate: Status;
  drivers: GateDrivers;
  nextEventDays: number | null;
  nextEventLabel: string | null;
  horizonKey: ThresholdHorizon;
  ivThresholds: HorizonIvThresholds | null;
  eventWindow: HorizonEventThresholds | null;
  gateDisabled: boolean;
  pctl: number | null | undefined;
  avail?: ThresholdsAvail;
}): RowExplanation {
  const {
    iv,
    hasIv,
    ivSt,
    proxStatus,
    gate,
    drivers,
    nextEventDays,
    nextEventLabel,
    ivThresholds,
    eventWindow,
    gateDisabled,
    pctl,
    avail = 'ready',
  } = args;

  const basisLabel = iv.basis === 'rank' ? 'IV rank' : iv.basis === 'absolute' ? 'IV' : '—';
  const unit = iv.basis === 'rank' ? '0–100' : iv.basis === 'absolute' ? '%' : 'none';

  const decidingReason = rowDecidingReason(gate, drivers, iv.basis, avail);
  const combination = rowCombinationPhrase(ivSt, proxStatus, gate, drivers, iv.basis, avail);
  const pctlFormatted = pctl != null ? `${pctl} (does not determine this gate)` : '—';

  // IV Observed & Rule Explanation
  let ivObserved = 'Missing';
  if (hasIv && iv.value !== null) {
    ivObserved = formatGateIv(iv).text;
  }

  let ivRuleExplanation = '';
  if (avail !== 'ready') {
    ivRuleExplanation = 'Thresholds unavailable; rule cannot be evaluated';
  } else if (gateDisabled) {
    ivRuleExplanation = 'IV gate disabled for this horizon (ungated)';
  } else if (!hasIv) {
    ivRuleExplanation = 'Missing reading on gated horizon → CAUTION';
  } else if (ivThresholds) {
    const passMax = iv.basis === 'rank' ? ivThresholds.rank_pass_max : ivThresholds.abs_pass_max;
    const cautionMax = iv.basis === 'rank' ? ivThresholds.rank_caution_max : ivThresholds.abs_caution_max;
    const unitSuffix = iv.basis === 'absolute' ? '%' : '';

    if (passMax === null) {
      ivRuleExplanation = 'Ungated basis → PASS';
    } else {
      ivRuleExplanation = ivInterval(passMax, cautionMax, unitSuffix);
    }
  }

  // Event Observed & Rule Explanation
  let eventObserved = 'No event date available';
  if (nextEventDays !== null) {
    eventObserved = `${nextEventDays}d${nextEventLabel ? ` (${nextEventLabel})` : ''}`;
  }

  let eventRuleExplanation = '';
  if (avail !== 'ready') {
    eventRuleExplanation = 'Thresholds unavailable; rule cannot be evaluated';
  } else if (nextEventDays === null) {
    eventRuleExplanation = 'No event date available; existing gate applies no event penalty';
  } else if (eventWindow) {
    eventRuleExplanation = eventInterval(eventWindow);
  } else {
    eventRuleExplanation = 'No event window configured for this horizon';
  }

  return {
    basisLabel,
    unit,
    decidingReason,
    combination,
    ivObserved,
    ivRuleExplanation,
    eventObserved,
    eventRuleExplanation,
    pctlFormatted,
  };
}
