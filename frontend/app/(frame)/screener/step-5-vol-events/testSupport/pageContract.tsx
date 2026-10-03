/*
 * THE STEP 5 PAGE CONTRACT, shared by every Step 5 test file that walks it
 * (DOCC-3 plan S8): "nothing undeclared may speak, anywhere under the page
 * root", with a PIN per declared part and cell. Moved here out of
 * gateSummary.test.tsx, not copied, so the failed / loading / override states
 * (thresholdsUnavailable.test.tsx) are held to the SAME pins. It lives outside
 * __tests__ because jest would collect it there as an empty suite.
 */
import { screen } from '@testing-library/react';
import {
  missingReadingClause, headSentence, causesSentence, ivThresholdSentence,
  eventWindowSentence, thresholdsUnavailableSentence, ivOverrideSentence,
  MISSING_READING_CLAIM, rowDecidingReason,
  type MissingReadingClaim, type GateCause, type GateCounts, type IvBand, type ThresholdsAvail,
} from '../gateSummary';
import { STATUS_LABEL, type Status } from '@/lib/status';
import { formatIv, type IvBasis } from '@/lib/ivBasis';
import { eventVolGateTooltip, gateDrivers } from '@/lib/statusTooltips';
import { useIvThresholdsStore, effectiveIvThresholds, ivOverrideFor } from '@/lib/ivThresholdsStore';
import {
  useEventThresholdsStore, getEventWindow, type ThresholdHorizon,
} from '@/lib/eventThresholdsStore';
import { useScanStore } from '@/lib/scanStore';

/** The whole gate-summary line. BY TEST ID, not by text: the banner is three
 *  separate elements now, and `getByText` returns only the element DIRECTLY
 *  holding the matched text -- which would be one sentence out of three.
 *  (`getNodeText` reads a node's own text children, not its descendants'.)
 *  Scoping to this container also keeps the per-row tooltip out of the match:
 *  it deliberately shares the banner's wording, so an unscoped query finds
 *  two nodes and throws. */
/** What the page SHOULD publish as `data-avail`, derived from the stores
 *  rather than read back off the page (DOCC-3 plan §2.4). */
export function availFromStores(): ThresholdsAvail {
  const iv = useIvThresholdsStore.getState();
  const ev = useEventThresholdsStore.getState();
  if (iv.status === 'failed' || ev.status === 'failed') return 'failed';
  return effectiveIvThresholds(iv.thresholds, iv.overrides) !== null && ev.thresholds !== null
    ? 'ready' : 'loading';
}

/** The error the page must quote: the IV store's first, then the event store's. */
export function availErrorFromStores(): string | null {
  const iv = useIvThresholdsStore.getState();
  const ev = useEventThresholdsStore.getState();
  return iv.status === 'failed' ? iv.error : ev.status === 'failed' ? ev.error : null;
}

export function banner(): HTMLElement {
  const el = gateCopy().querySelector<HTMLElement>('[data-line="summary"]');
  if (el === null) throw new Error('the page rendered no gate-summary line');
  return el;
}

/** Every sentence in the header region, keyed by `data-part`. Scoped to the
 *  WHOLE header, not the summary line: a gloss added to the threshold sentence
 *  above it is exactly what round 1 measured shipping 1724/1724 green. */
export function partsOf(): Record<string, HTMLElement> {
  const out: Record<string, HTMLElement> = {};
  for (const el of gateCopy().querySelectorAll<HTMLElement>('[data-part]')) {
    out[el.getAttribute('data-part') as string] = el;
  }
  return out;
}

/** The claim an element publishes, read off its attributes. */
export function claimFrom(el: HTMLElement): { rows: number; claim: MissingReadingClaim } {
  const read = (name: string): string => {
    const v = el.getAttribute(`data-claim-${name}`);
    // A field the page stops rendering must fail loudly here, not arrive as
    // `undefined` and quietly satisfy a comparison with another `undefined`.
    if (v === null) throw new Error(`the banner publishes no data-claim-${name}`);
    return v;
  };
  return {
    rows: Number(read('rows')),
    claim: {
      side:        read('side'),
      asserted:    read('asserted'),
      denied:      read('denied'),
      combination: read('combination'),
    } as MissingReadingClaim,
  };
}

/** EVERY sentence this page may say, in render order, and the pin that holds
 *  each one to its own published data. A part is legal only if it appears here,
 *  and appearing here means SUPPLYING A PIN -- adding a name to a list was not
 *  enough. Round 1 measured that: a lying `data-part="note"` span plus its name
 *  in a bare whitelist shipped 51/51 GREEN. */
export const PART_PINS: Record<string, (el: HTMLElement) => void> = {
  'step-label': (el) => expect(el.textContent).toBe('STEP 5 OF 7'),
  'page-title': (el) => expect(el.textContent).toBe('Volatility + Events'),

  /* WHICH BRANCH, AND WHETHER IT IS THE RIGHT ONE FOR THE STATE. Round 2
   * measured the previous pin -- an anchored alternation over the four sayable
   * sentences -- letting a GATED horizon print "IV gate disabled for this
   * horizon." at 67/67 green: it graded which sentences were sayable, never
   * which one the page was entitled to say. The branch is published now and
   * checked against the gate config the page is actually applying. */
  'iv-thresholds': (el) => {
    const root = page();
    const ivGated = root.getAttribute('data-iv-gated') === 'true';
    const candidates = Number(root.getAttribute('data-candidates'));
    const bands = JSON.parse(el.getAttribute('data-iv-bands') as string) as IvBand[];

    // THE BRANCH THE PAGE IS ENTITLED TO TAKE, from the state it publishes.
    expect(el.getAttribute('data-branch')).toBe(
      !ivGated           ? 'disabled'
      : candidates === 0 ? 'no-scan'
      : bands.length > 0 ? 'thresholds'
      :                    'no-reading',
    );

    // ...and the sentence that branch must say, by EQUALITY. No `\d+` holes.
    const SAYS: Record<string, () => string> = {
      'disabled':   () => 'IV gate disabled for this horizon.',
      'no-scan':    () => 'Run a scan to see the volatility and event gates.',
      'no-reading': () => 'No volatility reading for these candidates.',
      'thresholds': () => ivThresholdSentence(bands),
    };
    expect(el.textContent).toBe(SAYS[el.getAttribute('data-branch') as string]());

    /* AND THE BANDS ARE THE ONES THE GATE READS. Without this the sentence is
     * pinned only to its own published data, which is the circularity the whole
     * loop exists to remove. The boundary cases in the table below then tie the
     * same numbers to actual row verdicts. */
    // DOCC-3: the cast to ThresholdHorizon is authorised (plan round 2 note).
    const horizon = root.getAttribute('data-horizon') as ThresholdHorizon;
    // NO CAST. `k` narrows to 'rank' | 'abs', so the template literals below type
    // as the real keys of HorizonIvThresholds. The cast that was here asserted an
    // index signature the interface does not have, which tsc rejected outright --
    // and a cast to a looser shape would have been the same false-confidence move
    // this loop keeps removing from the assertions themselves.
    // DOCC-3 (authorised change 1): the EFFECTIVE record -- fetched plus the
    // Settings override -- because that is what the badges apply, and the
    // header must quote the same ceiling they grade against.
    const st = useIvThresholdsStore.getState();
    const store = effectiveIvThresholds(st.thresholds, st.overrides);
    for (const b of bands) {
      const k = b.basis === 'rank' ? 'rank' : 'abs';
      expect([b.basis, b.passMax, b.cautionMax])
        .toEqual([b.basis, store?.[horizon]?.[`${k}_pass_max`], store?.[horizon]?.[`${k}_caution_max`]]);
    }
  },

  /* THE WINDOW THE GATE APPLIES, NOT THE ONE THE SENTENCE FANCIES. Three
   * things quote this window -- this sentence, the root attributes every row
   * tooltip is rebuilt from, and the ternary that grades every row -- and
   * nothing compared them, exactly as nothing compared the IV bands before the
   * pin above it was written. The sentence is built from the STORE here, never
   * from the element's own attributes: reading it back off the node it renders
   * is the circularity this loop exists to remove. */
  'event-window': (el) => {
    const root = page();
    const horizon = root.getAttribute('data-horizon') as ThresholdHorizon;
    const ev = useEventThresholdsStore.getState().thresholds;
    if (ev === null) throw new Error('event-window rendered with no event record in the store');
    // The window the scan APPLIED when the result echoes one (0b41781: a Step-3
    // override such as SemiAnnual_*'s 7/30), else the horizon's YAML window.
    const echoed = useScanStore.getState().scanResult?.event_window;
    const w = echoed ? { ...getEventWindow(horizon, ev), ...echoed } : getEventWindow(horizon, ev);

    // 1. The sentence, by equality, over the window the gate reads.
    expect(el.textContent).toBe(eventWindowSentence(w));

    /* 2. The pair the row tooltips quote is that same window. Measured as
     *    LARGELY REDUNDANT and kept deliberately: publishing `evReject + 1`
     *    here is caught eight ways over by the gate cell's tooltip pin, which
     *    rebuilds the tooltip from these very attributes. It is the only thing
     *    holding them where NO row renders -- the no-scan branch, where that
     *    pin never runs -- and it is one comparison. */
    expect([root.getAttribute('data-ev-reject'), root.getAttribute('data-ev-caution')])
      .toEqual([String(w.reject_days), String(w.caution_days)]);

    /* 3. ...and every row on screen got the verdict THIS SENTENCE PROMISES it.
     *    Strict `<`, because that is what the sentence now says. It used to say
     *    "Earnings within {caution} days -> CAUTION; within {reject} days ->
     *    REJECT" -- an inclusive reading of a window the gate, the tooltip and
     *    backend _rule_event all apply exclusively -- so a row sitting exactly
     *    on day 21 was announced REJECT and graded CAUTION, and nothing here
     *    went red. This turns the claim into an observation over whatever rows
     *    the scenario rendered; the two boundary cases below put a row ON each
     *    edge so the comparison is not vacuous.
     *
     *    AND IT IS THE ONLY THING CATCHING A MASKED SUB-VERDICT. `gate` is
     *    worstStatus(iv, event), so on an IV-REJECTed row the event side can be
     *    corrupted invisibly: flipping the gate's far-event branch from PASS to
     *    CAUTION leaves gate, head, causes and tooltip identical. Measured --
     *    with this loop the mutation fails 2 tests, without it 1, and the one
     *    it stops failing is the IV-REJECT row added below for exactly this. */
    for (const row of root.querySelectorAll<HTMLElement>('[data-status]')) {
      const raw = row.querySelector('[data-cell="event"]')?.getAttribute('data-days') ?? '';
      if (raw === '') continue;
      const days = Number(raw);
      expect([raw, row.querySelector('[data-cell="gate"]')?.getAttribute('data-side-event')])
        .toEqual([raw, days < w.reject_days ? 'REJECT'
                     : days < w.caution_days ? 'CAUTION'
                     : 'PASS']);
    }
  },

  'gate-rule': (el) => expect(el.textContent).toBe('Gate = worst of IV and event proximity.'),

  /* DOCC-3: THE OVERRIDE LABEL, against the STORES' override and YAML value --
   * never the part's own attributes alone, which is the circularity this file
   * keeps removing. */
  'iv-override': (el) => {
    const root = page();
    const st = useIvThresholdsStore.getState();
    const o = ivOverrideFor(root.getAttribute('data-horizon') as ThresholdHorizon, st.thresholds, st.overrides);
    expect(o).not.toBeNull();
    expect([el.getAttribute('data-override'), el.getAttribute('data-yaml')])
      .toEqual([String(o!.value), String(o!.yaml)]);
    expect(el.textContent).toBe(ivOverrideSentence(o!.value, o!.yaml));
  },

  /* DOCC-3: NO THRESHOLDS, NO NUMBERS. The availability and the error are
   * checked against the stores, and the sentence by equality. */
  'thresholds-unavailable': (el) => {
    const avail = availFromStores();
    expect(avail).not.toBe('ready');
    expect([page().getAttribute('data-avail'), el.getAttribute('data-avail')]).toEqual([avail, avail]);
    const err = availErrorFromStores();
    expect(el.getAttribute('data-error')).toBe(err ?? '');
    expect(el.textContent).toBe(thresholdsUnavailableSentence(avail as Exclude<ThresholdsAvail, 'ready'>, err));
  },

  'thresholds-retry': (el) => {
    expect(availFromStores()).toBe('failed');
    expect(el.tagName).toBe('BUTTON');
    expect(el.textContent).toBe('Retry');
  },

  // THE COUNTS AND NOTHING ELSE: equality against the page's own builder, run
  // over the counts the part publishes. The counts themselves are tied to the
  // rows on screen in `expectPageCopy` below.
  'head': (el) => expect(el.textContent).toBe(
    headSentence(JSON.parse(el.getAttribute('data-counts') as string) as GateCounts),
  ),

  /* EQUALITY, NOT PUNCTUATION. Round 1 measured a "one sentence" rule admitting
   * "; these rows are safe to trade as if they were clean." at 51/51 green
   * while REJECTING a true sentence at the same site -- round 4's finding
   * reproduced. The words come from CAUSE_LABEL, pinned whole by its own test. */
  'causes': (el) => expect(el.textContent).toBe(
    causesSentence(
      JSON.parse(el.getAttribute('data-causes') as string) as GateCause[],
      el.getAttribute('data-overlap') === 'true',
    ),
  ),

  // THE SENTENCE IS THE CLAIM RENDERED, AND THE CLAIM IS THE MODULE CONSTANT.
  'missing-reading': (el) => {
    const claimed = claimFrom(el);
    expect(claimed.claim).toEqual(MISSING_READING_CLAIM);
    expect(el.textContent).toBe(missingReadingClause(claimed.rows, claimed.claim));
  },
};

/** The order the page must render them in. */
export const PART_ORDER = [
  'step-label', 'page-title',
  // DOCC-3 (authorised change 3): the unavailable pair stands where the three
  // threshold parts would; the list is a superset, the ready parts stay.
  'thresholds-unavailable', 'thresholds-retry',
  'iv-thresholds', 'iv-override', 'event-window', 'gate-rule',
  'head', 'causes', 'missing-reading',
] as const;

/* ── THE ROW CELLS ────────────────────────────────────────────────────────
 * Each declares what it is and publishes what it renders, so its words can be
 * pinned against its own data. Round 2 put a lying `title` on the IV cell and
 * on the event cell, and a lying tooltip on every row -- 67/67 green each,
 * because the contract looked only inside the header.
 *
 * WHERE A SHARED ATOM OWNS THE SUBTREE (WatchStar, OpenChartButton) the pin
 * checks what THIS PAGE can inject through props, and the atom's own fixed copy
 * is listed because a closed statement needs it. That couples this file to
 * those atoms' wording: if one changes, one line here changes with it. That is
 * the price of "nothing undeclared may speak", and it is worth paying. */
export const CELL_PINS: Record<string, (el: HTMLElement, row: HTMLElement) => void> = {
  chart: (el) => {
    expect(el.textContent).toBe('📈');
    expect(titlesIn(el)).toEqual(['Open in Chart']);
  },
  watch: (el) => {
    const sym = el.getAttribute('data-symbol') as string;
    expect(el.textContent).toBe('');
    expect(titlesIn(el).every((t) => t === 'Add to watchlist' || t === 'In watchlist')).toBe(true);
    expect(ariaLabelsIn(el).every(
      (a) => a === `Add ${sym} to watchlist` || a === `Remove ${sym} from watchlist`,
    )).toBe(true);
  },
  symbol:  (el) => expect(el.textContent).toBe(el.getAttribute('data-value')),
  company: (el) => expect(el.textContent).toBe(el.getAttribute('data-value')),

  iv: (el) => {
    const basis = el.getAttribute('data-iv-basis') as IvBasis;
    const raw = el.getAttribute('data-iv-value') as string;
    const sym = (el.closest('[data-status]')?.querySelector('[data-cell="symbol"]')
      ?.getAttribute('data-value')) as string;
    const shown = formatIv({ basis, value: raw === '' ? null : Number(raw) } as never, sym);
    expect(el.textContent).toBe(`${shown.text}${shown.suffix}`);
    expect(el.getAttribute('title')).toBe(shown.title);
  },

  pctl: (el) => {
    const v = el.getAttribute('data-value') as string;
    expect(el.textContent).toBe(v === '' ? '—' : v);
    expect(titlesIn(el)).toEqual([]);
  },

  event: (el) => {
    const days = el.getAttribute('data-days') as string;
    const label = el.getAttribute('data-label') as string;
    expect(el.textContent).toBe(days === '' ? '—' : `${days}d`);
    expect(titlesIn(el)).toEqual(days === '' || label === '' ? [] : [label]);
  },

  /* THE BADGE AND THE TOOLTIP, both against the row's own published data.
   * The tooltip is the thing a trader hovers to ask "why CAUTION?" and round 2
   * appended "A missing volatility reading is graded PASS on the volatility
   * side; this row is safe to treat as clean." to every one of them at
   * 1740/1740 green. Rebuilt from the published sub-verdicts here, so an
   * appended word has nothing to come from. */
  gate: (el) => {
    const gate = el.getAttribute('data-gate') as Status;
    const ivSt = el.getAttribute('data-side-volatility') as Status;
    const evSt = el.getAttribute('data-side-event') as Status;
    const root = page();
    const row = el.closest('[data-status]') as HTMLElement;
    const ivCell = row.querySelector('[data-cell="iv"]') as HTMLElement;
    const evCell = row.querySelector('[data-cell="event"]') as HTMLElement;
    const basis = ivCell.getAttribute('data-iv-basis') as IvBasis;
    const rawIv = ivCell.getAttribute('data-iv-value') as string;
    const days = evCell.getAttribute('data-days') as string;

    // DOCC-3 (authorised change 2): with no thresholds in hand the tooltip is
    // exactly the unavailable sentence, and neither side has a verdict.
    const avail = root.getAttribute('data-avail') as ThresholdsAvail;
    expect(avail).toBe(availFromStores());
    if (avail !== 'ready') {
      const none: Status = avail === 'failed' ? 'NO_DATA' : 'PENDING';
      expect([gate, ivSt, evSt]).toEqual([none, none, none]);
      expect(el.querySelector('[role="tooltip"]')?.textContent)
        .toBe(thresholdsUnavailableSentence(avail, availErrorFromStores()));
      const noVerdictBadge = [...el.querySelectorAll('span')]
        .map((x) => x.textContent).filter((t) => t === STATUS_LABEL[gate]);
      expect(noVerdictBadge.length).toBeGreaterThan(0);
      return;
    }
    expect(el.querySelector('[role="tooltip"]')?.textContent).toBe(eventVolGateTooltip({
      ivRank: rawIv === '' ? null : Number(rawIv),
      ivBasis: basis,
      ivStatus: ivSt,
      nextEventDays: days === '' ? null : Number(days),
      proxStatus: evSt,
      evReject: Number(root.getAttribute('data-ev-reject')),
      evCaution: Number(root.getAttribute('data-ev-caution')),
      gate,
      drivers: gateDrivers({
        ivStatus: ivSt, proxStatus: evSt, gate,
        hasIv: basis !== 'none',
        ivGated: root.getAttribute('data-iv-gated') === 'true',
      }),
    }));

    // The badge's own word, beside the verdict it was given.
    const badge = [...el.querySelectorAll('span')]
      .map((x) => x.textContent).filter((t) => t === STATUS_LABEL[gate]);
    expect(badge.length).toBeGreaterThan(0);
  },

  'iv-status': (el, row) => {
    const root = page();
    const avail = root.getAttribute('data-avail') as ThresholdsAvail;
    const st = row.querySelector('[data-cell="gate"]')?.getAttribute('data-side-volatility') as Status;
    if (avail !== 'ready') {
      const none: Status = avail === 'failed' ? 'NO_DATA' : 'PENDING';
      expect(st).toBe(none);
      return;
    }
    const badge = [...el.querySelectorAll('span')].map((x) => x.textContent).filter((t) => t === STATUS_LABEL[st]);
    expect(badge.length).toBeGreaterThan(0);
  },

  'event-status': (el, row) => {
    const root = page();
    const avail = root.getAttribute('data-avail') as ThresholdsAvail;
    const st = row.querySelector('[data-cell="gate"]')?.getAttribute('data-side-event') as Status;
    if (avail !== 'ready') {
      const none: Status = avail === 'failed' ? 'NO_DATA' : 'PENDING';
      expect(st).toBe(none);
      return;
    }
    const badge = [...el.querySelectorAll('span')].map((x) => x.textContent).filter((t) => t === STATUS_LABEL[st]);
    expect(badge.length).toBeGreaterThan(0);
  },

  reason: (el, row) => {
    const root = page();
    const avail = root.getAttribute('data-avail') as ThresholdsAvail;
    if (avail !== 'ready') return;
    const gate = row.querySelector('[data-cell="gate"]')?.getAttribute('data-gate') as Status;
    const ivSt = row.querySelector('[data-cell="gate"]')?.getAttribute('data-side-volatility') as Status;
    const evSt = row.querySelector('[data-cell="gate"]')?.getAttribute('data-side-event') as Status;
    const ivCell = row.querySelector('[data-cell="iv"]') as HTMLElement;
    const basis = ivCell.getAttribute('data-iv-basis') as IvBasis;
    const ivGated = root.getAttribute('data-iv-gated') === 'true';
    const d = gateDrivers({
      ivStatus: ivSt, proxStatus: evSt, gate,
      hasIv: basis !== 'none',
      ivGated,
    });
    expect(el.textContent).toContain(rowDecidingReason(gate, d, basis));
  },

  disclosure: (el, row) => {
    const sym = row.querySelector('[data-cell="symbol"]')?.getAttribute('data-value');
    const btn = el.querySelector('button');
    expect(btn).not.toBeNull();
    expect(btn?.getAttribute('aria-controls')).toBe(`disclosure-${sym}`);
    expect(btn?.getAttribute('aria-expanded')).toBeDefined();
  },

  'pctl-context': (el) => {
    expect(el.textContent).toBe('IV PCTL (Context only):');
  },
};

export const PROSE_ATTRS = ['title', 'aria-label', 'aria-labelledby', 'aria-describedby', 'aria-hidden'] as const;

export function attrsIn(el: HTMLElement, name: string): string[] {
  return [el, ...el.querySelectorAll<HTMLElement>('*')]
    .map((x) => x.getAttribute(name))
    .filter((v): v is string => v !== null);
}
export const titlesIn     = (el: HTMLElement) => attrsIn(el, 'title');
export const ariaLabelsIn = (el: HTMLElement) => attrsIn(el, 'aria-label');

/** The component root. The contract's region is the PAGE, not a div inside it. */
export function page(): HTMLElement {
  return screen.getByTestId('step-5');
}

/** The header region, still named for the tests that only care about the copy. */
export function gateCopy(): HTMLElement {
  return screen.getByTestId('step-5-header');
}

/** Own text: the node's OWN text children, not its descendants'. */
export function ownText(el: Element): string {
  return [...el.childNodes]
    .filter((n) => n.nodeType === 3)
    .map((n) => n.textContent ?? '')
    .join('')
    .trim();
}

/** A readable name for a node that failed to be declared. */
export function nodeId(el: HTMLElement): string {
  const attrs = ['data-part', 'data-cell', 'data-line', 'data-status']
    .map((a) => (el.getAttribute(a) === null ? '' : `${a}="${el.getAttribute(a)}"`))
    .filter(Boolean).join(' ');
  return `<${el.tagName.toLowerCase()}${attrs === '' ? '' : ' ' + attrs}> ${JSON.stringify(
    (ownText(el) || PROSE_ATTRS.map((a) => el.getAttribute(a)).filter(Boolean).join('|')).slice(0, 60),
  )}`;
}

/** Which declared owner a speaking node belongs to. Order matters: a cell is
 *  inside a row, so cells are asked first. */
export const OWNERS: Array<{ name: string; of: (el: HTMLElement) => HTMLElement | null }> = [
  { name: 'part', of: (el) => el.closest('[data-part]') },
  { name: 'colheaders', of: (el) => el.closest('[data-colheaders]') },
  { name: 'rules-strip', of: (el) => el.closest('[data-rules-strip]') },
  { name: 'disclosure-panel', of: (el) => el.closest('[data-disclosure-panel]') },
  { name: 'cell', of: (el) => el.closest('[data-cell]') },
  { name: 'row', of: (el) => (el.hasAttribute('data-status') ? el : null) },
];

/** THE CONTRACT: nothing undeclared may speak, anywhere under the page root.
 *
 *  THIS IS THE THIRD SHAPE OF IT, and the first two were both REGIONS. The
 *  first graded `[data-line="summary"]`; round 1 put a contradicting sentence
 *  one line above it and shipped 1724/1724. The second graded the header;
 *  round 2 put the same sentence one line BELOW it and shipped 1740/1740, then
 *  found five more outside: every row tooltip, two row-cell `title`s, an
 *  `aria-label` one element up from the claim, and an `aria-hidden` that
 *  deletes the true clause for screen-reader users. Widening the region was
 *  the losing move three rounds running.
 *
 *  So this is not a region. Every element under the root that puts text on
 *  screen or carries prose in an attribute must resolve to a DECLARED owner
 *  with a PIN, and the pin derives its expectation from that owner's own
 *  published data. Anything undeclared is red wherever it is. */
export function expectPageCopy() {
  const root = page();
  const owners = new Map<HTMLElement, string>();

  for (const el of root.querySelectorAll<HTMLElement>('*')) {
    const speaks = ownText(el) !== ''
      || PROSE_ATTRS.some((a) => el.getAttribute(a) !== null);
    if (!speaks) continue;

    const hit = OWNERS.map((o) => [o.name, o.of(el)] as const).find(([, owner]) => owner !== null);
    // Named in the expectation so a failure says WHICH node is undeclared.
    expect(hit === undefined ? nodeId(el) : 'declared').toBe('declared');
    owners.set(hit![1] as HTMLElement, hit![0]);
  }

  for (const [owner, kind] of owners) {
    if (kind === 'part') {
      const name = owner.getAttribute('data-part') as string;
      const pin = PART_PINS[name];
      expect(typeof pin === 'function' ? 'pinned' : `UNPINNED PART: ${name}`).toBe('pinned');
      pin(owner);
    } else if (kind === 'colheaders') {
      expect([...owner.children].map((c) => c.textContent).filter((t) => t !== ''))
        .toEqual(JSON.parse(owner.getAttribute('data-colheaders') as string));
    } else if (kind === 'rules-strip') {
      const horizon = root.getAttribute('data-horizon') as ThresholdHorizon;
      const scanEventWindow = useScanStore.getState().scanResult?.event_window;
      const hasScan = useScanStore.getState().scanResult !== undefined;
      const expectedProvenance = scanEventWindow
        ? 'Recorded scan event window'
        : hasScan
          ? 'Legacy scan: current configuration fallback'
          : 'Current backend configuration';
      expect(owner.querySelector('[data-provenance]')?.textContent).toBe(expectedProvenance);
      expect(owner.querySelector('[data-horizon-tag]')?.textContent).toBe(`Horizon: ${horizon}`);
    } else if (kind === 'disclosure-panel') {
      const sym = owner.getAttribute('data-symbol');
      expect(owner.getAttribute('id')).toBe(`disclosure-${sym}`);
      expect(owner.getAttribute('role')).toBe('region');
    } else if (kind === 'cell') {
      const name = owner.getAttribute('data-cell') as string;
      const pin = CELL_PINS[name];
      expect(typeof pin === 'function' ? 'pinned' : `UNPINNED CELL: ${name}`).toBe('pinned');
      pin(owner, owner.closest('[data-status]') as HTMLElement);
    } else {
      // THE TINT, against the verdict its own badge carries. Round 2 tinted
      // rows with the event sub-verdict and shipped 1740/1740 -- a PASS band
      // beside a REJECT badge -- because nothing read the third consumer of
      // `gate`.
      expect(owner.getAttribute('data-status'))
        .toBe(owner.querySelector('[data-cell="gate"]')?.getAttribute('data-gate'));
    }
  }
}

/** The claim the page is MAKING, read off the DOM rather than retyped here.
 *  Null when the banner carries no missing-reading sentence at all. */
export function claimOf(): { rows: number; claim: MissingReadingClaim } | null {
  const el = gateCopy().querySelector<HTMLElement>('[data-part="missing-reading"]');
  return el === null ? null : claimFrom(el);
}

/** Both sides of the gate, named exactly as the claim's `side` field names
 *  them -- so a test can turn that field into an observation with no decode
 *  table standing between the two. */
export const SIDES = ['volatility', 'event'] as const;

export function rowOf(symbol: string): HTMLElement {
  const el = document.querySelector<HTMLElement>(`[data-row="${symbol}"]`);
  if (el === null) throw new Error(`no rendered row for ${symbol}`);
  return el;
}

export function sideVerdict(symbol: string, side: MissingReadingClaim['side']): Status {
  const v = rowOf(symbol).getAttribute(`data-side-${side}`);
  if (v === null) throw new Error(`row ${symbol} publishes no ${side} sub-verdict`);
  return v as Status;
}

export function gateOf(symbol: string): Status {
  const v = rowOf(symbol).getAttribute('data-gate');
  if (v === null) throw new Error(`row ${symbol} publishes no gate verdict`);
  return v as Status;
}

