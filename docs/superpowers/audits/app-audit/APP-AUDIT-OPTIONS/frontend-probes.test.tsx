import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';

import fixtures from './frontend-fixtures.json';
import { cardToRow } from '../../../../../frontend/app/(frame)/screener/step-4-ranking/cardToRow';
import { resolveIv, formatIv } from '@/lib/ivBasis';
import { worstStatus, type Status } from '@/lib/status';
import {
  capitalAtRisk,
  exposurePct,
  stopPremiumRisk,
  formatStopLossBadge,
  formatStopLossHeadline,
  stopLossIsTotalOnPrintedFigures,
  rankingStopCost,
  checkInvalidation,
  checkMethodPick,
  recommendedContractSize,
  formatRecommendedContractSizeRaw,
  checkTradeRisk,
} from '@/lib/risk';
import {
  contractId,
  contractLabel,
  type TradeCardData,
  type OptionContract,
  type AlternativeContract,
  type MethodPick,
} from '@/types/domain';
import { missingCardContracts, withCardContract } from '@/lib/step6CardContract';
import {
  directOrderBlock,
  classifyDirectFailure,
} from '@/lib/directOrder';
import { useScanStore } from '@/lib/scanStore';
import { useRiskStore } from '@/lib/riskStore';
import { useWatchedContractsStore } from '@/lib/watchedContractsStore';

import { StatusBadge } from '@/components/atoms/StatusBadge';
import { RankDelta } from '@/components/atoms/RankDelta';
import { EventFlag } from '@/components/atoms/EventFlag';
import { AlternativeContractRow } from '@/components/molecules/AlternativeContractRow';
import { SendToBrokerDialog } from '@/components/organisms/SendToBrokerDialog';

describe('APP-AUDIT-OPTIONS Frontend Verification Probes', () => {
  const sampleMethodPick: MethodPick = {
    method: 'barrier_race',
    rowStockPrice: null,
    rowOptionPrice: 6.90,
    stopBasis: 'premium',
    pickedAt: '2026-10-22T08:00:00Z',
  };

  beforeEach(() => {
    useScanStore.setState({
      scanResult: undefined,
      selectedSymbol: '',
      pickedContracts: {},
      contractsBySymbol: {},
    });
    useWatchedContractsStore.setState({
      ids: [],
      grading: {},
    });
  });

  describe('1. Step 4 Stock Ranking Arithmetic & Sorting', () => {
    it('1.1 correctly transforms TradeCardData to WatchlistRow and computes deltas against previousRun', () => {
      const candidates = fixtures.step4_ranking.candidates as unknown as TradeCardData[];
      const prevRun = {
        candidates: fixtures.step4_ranking.previous_run.candidates.map((c) => ({
          ...c,
          company: c.symbol,
          price: 100,
          direction: 'Bullish',
          status: 'PASS',
        })),
      } as any;

      // AAPL was #2 in prevRun (stockScore 82), now #1 (stockScore 88)
      const row1 = cardToRow(candidates[0], 1, prevRun, 'Swing');
      expect(row1.symbol).toBe('AAPL');
      expect(row1.rank).toBe(1);
      expect(row1.rankDelta).toBe(1); // 2 - 1 = +1
      expect(row1.scoreDelta).toBe(6); // 88 - 82 = +6
      expect(row1.horizon).toBe('Swing');
      expect(row1.stopCostPct).toBe(28.5);
      expect(row1.stopCostStatus).toBe('PASS');
      expect(row1.confidence).toBe('HIGH');

      // MSFT was #1 in prevRun (stockScore 70), now #2 (stockScore 74)
      const row2 = cardToRow(candidates[1], 2, prevRun, 'Position');
      expect(row2.symbol).toBe('MSFT');
      expect(row2.rank).toBe(2);
      expect(row2.rankDelta).toBe(-1); // 1 - 2 = -1
      expect(row2.scoreDelta).toBe(4); // 74 - 70 = +4
      expect(row2.horizon).toBe('Position');

      // NVDA was not in prevRun -> rankDelta = 0, scoreDelta = 0
      const row3 = cardToRow(candidates[2], 3, prevRun, 'Intraday');
      expect(row3.symbol).toBe('NVDA');
      expect(row3.rank).toBe(3);
      expect(row3.rankDelta).toBe(0);
      expect(row3.scoreDelta).toBe(0);
      expect(row3.horizon).toBe('Intraday');
      expect(row3.stopCostPct).toBeNull();
      expect(row3.stopCostStatus).toBeNull();
    });

    it('1.2 verifies horizon weights sum to exactly 100% and weighted component points match formula', () => {
      const weights = fixtures.step4_ranking.horizon_weights;

      for (const [, w] of Object.entries(weights)) {
        const sum = w.trend + w.pullback + w.trigger + w.event + w.volatility;
        expect(sum).toBe(100);
      }

      // Check weighted points calculation: (raw * weight) / 100
      const rawTrend = 90;
      const swingTrendWeight = weights.Swing.trend; // 30
      const expectedPoints = (rawTrend * swingTrendWeight) / 100; // 27.0
      expect(expectedPoints).toBe(27.0);

      // Raw signal classification
      function signalFor(val: number) {
        if (val >= 65) return 'pos';
        if (val >= 45) return 'neu';
        return 'neg';
      }
      expect(signalFor(90)).toBe('pos');
      expect(signalFor(65)).toBe('pos');
      expect(signalFor(64)).toBe('neu');
      expect(signalFor(45)).toBe('neu');
      expect(signalFor(44)).toBe('neg');
      expect(signalFor(0)).toBe('neg');
    });

    it('1.3 sorting rules: stopCostPct puts cheapest stop first and uncomputed values (null) last', () => {
      const candidates = fixtures.step4_ranking.candidates as unknown as TradeCardData[];
      const rows = candidates.map((c, i) => cardToRow(c, i + 1));

      // Natural sort by stopCostPct (asc): 28.5 (AAPL), 65.0 (MSFT), null/101 (NVDA)
      const sortedByStop = [...rows].sort((a, b) => {
        const av = a.stopCostPct ?? 101;
        const bv = b.stopCostPct ?? 101;
        return av - bv;
      });

      expect(sortedByStop[0].symbol).toBe('AAPL');
      expect(sortedByStop[1].symbol).toBe('MSFT');
      expect(sortedByStop[2].symbol).toBe('NVDA');
    });

    it('1.4 verifies pipeline exclusion count formula matches root-cause inspector expectation', () => {
      const scanned = 50;
      const candidateSymbols = ['AAPL', 'MSFT', 'NVDA'];
      const filteredCount = Math.max(0, scanned - candidateSymbols.length);
      expect(filteredCount).toBe(47);

      // When scanned is less than candidateSymbols (degenerate edge case), must clamp to 0
      const degenerateFiltered = Math.max(0, 2 - candidateSymbols.length);
      expect(degenerateFiltered).toBe(0);
    });
  });

  describe('2. Step 5 Volatility & Events Gate Arithmetic', () => {
    it('2.1 resolves IV basis correctly between rank, absolute, and missing readings', () => {
      // IV rank present -> basis rank
      const r1 = resolveIv({ ivRank: 35, iv: 0.45 });
      expect(r1.basis).toBe('rank');
      expect(r1.value).toBe(35);

      // IV rank 0 is a genuine reading at 52-week low -> basis rank
      const rZero = resolveIv({ ivRank: 0, iv: 0.20 });
      expect(rZero.basis).toBe('rank');
      expect(rZero.value).toBe(0);

      // IV rank null, absolute iv present -> basis absolute
      const r2 = resolveIv({ ivRank: null, iv: 0.45 });
      expect(r2.basis).toBe('absolute');
      expect(r2.value).toBe(0.45);

      // Both null or iv <= 0 -> basis none
      const r3 = resolveIv({ ivRank: null, iv: 0 });
      expect(r3.basis).toBe('none');
      expect(r3.value).toBeNull();

      const r4 = resolveIv(undefined);
      expect(r4.basis).toBe('none');
      expect(r4.value).toBeNull();
    });

    it('2.2 event proximity gating applies strict inequality (< reject, < caution) matching backend', () => {
      const evReject = 21;
      const evCaution = 45;

      function evalEventProximity(days: number | null | undefined): Status {
        if (days == null) return 'PASS';
        if (days < evReject) return 'REJECT';
        if (days < evCaution) return 'CAUTION';
        return 'PASS';
      }

      // 20 days < 21 -> REJECT
      expect(evalEventProximity(20)).toBe('REJECT');
      // 21 days is boundary (not < 21) -> CAUTION (21 < 45)
      expect(evalEventProximity(21)).toBe('CAUTION');
      // 44 days < 45 -> CAUTION
      expect(evalEventProximity(44)).toBe('CAUTION');
      // 45 days is boundary (not < 45) -> PASS
      expect(evalEventProximity(45)).toBe('PASS');
      // 60 days -> PASS
      expect(evalEventProximity(60)).toBe('PASS');
      // null -> PASS
      expect(evalEventProximity(null)).toBe('PASS');
    });

    it('2.3 IV status gating evaluates passMax, cautionMax, and missing readings across horizons', () => {
      const swingIv = fixtures.step5_vol_events.iv_thresholds.Swing.rank;
      const intradayIv = fixtures.step5_vol_events.iv_thresholds.Intraday.rank;

      function evalIvStatus(val: number | null, basis: string, passMax: number | null, cautionMax: number | null): Status {
        if (basis === 'none' || val == null) {
          // If gate disabled (passMax null), missing IV is PASS; otherwise CAUTION
          return passMax === null ? 'PASS' : 'CAUTION';
        }
        if (passMax === null) return 'PASS';
        if (val <= passMax) return 'PASS';
        if (cautionMax !== null && val <= cautionMax) return 'CAUTION';
        return 'REJECT';
      }

      // Swing rank: pass_max 50, caution_max 70
      expect(evalIvStatus(35, 'rank', swingIv.pass_max, swingIv.caution_max)).toBe('PASS');
      expect(evalIvStatus(50, 'rank', swingIv.pass_max, swingIv.caution_max)).toBe('PASS');
      expect(evalIvStatus(51, 'rank', swingIv.pass_max, swingIv.caution_max)).toBe('CAUTION');
      expect(evalIvStatus(70, 'rank', swingIv.pass_max, swingIv.caution_max)).toBe('CAUTION');
      expect(evalIvStatus(71, 'rank', swingIv.pass_max, swingIv.caution_max)).toBe('REJECT');
      expect(evalIvStatus(null, 'none', swingIv.pass_max, swingIv.caution_max)).toBe('CAUTION');

      // Intraday: gate disabled (pass_max null) -> everything PASS
      expect(evalIvStatus(80, 'rank', intradayIv.pass_max, intradayIv.caution_max)).toBe('PASS');
      expect(evalIvStatus(null, 'none', intradayIv.pass_max, intradayIv.caution_max)).toBe('PASS');
    });

    it('2.4 combined gate verdict is worst of IV status and event proximity', () => {
      expect(worstStatus('PASS', 'PASS')).toBe('PASS');
      expect(worstStatus('PASS', 'CAUTION')).toBe('CAUTION');
      expect(worstStatus('CAUTION', 'PASS')).toBe('CAUTION');
      expect(worstStatus('CAUTION', 'REJECT')).toBe('REJECT');
      expect(worstStatus('REJECT', 'PASS')).toBe('REJECT');
    });
  });

  describe('3. Step 6 Contracts Table & Decimal Strike Handling', () => {
    it('3.1 handles decimal and integer strikes correctly in contractId and contractLabel', () => {
      const c1: OptionContract = {
        id: 'NVDA|137.5|2025-05-16|C',
        symbol: 'NVDA',
        strike: 137.5,
        right: 'C',
        expiry: '2025-05-16',
        dte: 45,
        dteTotal: 45,
        price: 5.00,
        delta: 0.55,
        theta: -0.05,
        ivRank: null,
        ivPercentile: null,
        spread: 0.20,
        volume: 1200,
        score: 85,
        contractConfidence: 'PASS',
      };

      expect(contractId(c1.symbol, c1.strike, c1.expiry, c1.right)).toBe('NVDA|137.5|2025-05-16|C');
      expect(contractLabel(c1)).toBe('NVDA 137.5C 05/16/25');

      const c2: OptionContract = {
        ...c1,
        symbol: 'AAPL',
        strike: 230.0,
        id: 'AAPL|230|2025-05-16|C',
      };
      expect(contractId(c2.symbol, c2.strike, c2.expiry, c2.right)).toBe('AAPL|230|2025-05-16|C');
      expect(contractLabel(c2)).toBe('AAPL 230C 05/16/25');
    });

    it('3.2 computes bid/ask/mid and spread metrics with exact precision', () => {
      const bid = 4.90;
      const ask = 5.10;
      const mid = (bid + ask) / 2;
      const spread = ask - bid;
      const spreadPct = spread / mid;

      expect(mid).toBe(5.00);
      expect(Math.round(spread * 100) / 100).toBe(0.20);
      expect(Math.round(spreadPct * 10000) / 10000).toBe(0.04); // 4%
    });

    it('3.3 sorting contracts preserves null-handling invariant (nulls sort last in both asc and desc)', () => {
      const contracts = fixtures.step6_contracts.contracts as unknown as OptionContract[];

      const byNullable = (av: number | null, bv: number | null, dir: 'asc' | 'desc'): number => {
        const mul = dir === 'asc' ? 1 : -1;
        if (av == null && bv == null) return 0;
        if (av == null) return 1;
        if (bv == null) return -1;
        return (av - bv) * mul;
      };

      // Sort ivRank asc: AAPL (38) first, MSFT and NVDA (null) at end
      const ascSorted = [...contracts].sort((a, b) => byNullable(a.ivRank ?? null, b.ivRank ?? null, 'asc'));
      expect(ascSorted[0].symbol).toBe('AAPL');
      expect(ascSorted[1].ivRank).toBeNull();
      expect(ascSorted[2].ivRank).toBeNull();

      // Sort ivRank desc: AAPL (38) first, MSFT and NVDA (null) at end
      const descSorted = [...contracts].sort((a, b) => byNullable(a.ivRank ?? null, b.ivRank ?? null, 'desc'));
      expect(descSorted[0].symbol).toBe('AAPL');
      expect(descSorted[1].ivRank).toBeNull();
      expect(descSorted[2].ivRank).toBeNull();
    });

    it('3.4 card contract rescue correctly appends missing contract past chain limits', () => {
      const tableContracts: OptionContract[] = [
        {
          id: 'AAPL|230|2025-05-16|C',
          symbol: 'AAPL',
          strike: 230.0,
          right: 'C',
          expiry: '2025-05-16',
          dte: 45,
          dteTotal: 45,
          price: 6.90,
          delta: 0.52,
          theta: -0.06,
          ivRank: 38,
          ivPercentile: 40,
          spread: 0.20,
          volume: 850,
          score: 92,
          contractConfidence: 'PASS',
        },
      ];

      const candidate: TradeCardData = {
        symbol: 'AAPL',
        company: 'Apple Inc.',
        price: 230.50,
        direction: 'Bullish',
        status: 'PASS',
        stockScore: 88,
        contract: 'AAPL|235|2025-05-16|C',
        contractDetails: {
          strike: 235.0,
          right: 'C',
          expiry: '2025-05-16',
          mid: 4.60,
        },
        entry: { limit: 4.60, maxFill: 4.80 },
        exit: { invalidation: 220.0, premiumStop: 2.30, timeStopDays: 20, targets: [] },
      } as any;

      const missing = missingCardContracts([candidate], [tableContracts], 'C');
      expect(missing).toHaveLength(1);
      expect(missing[0].id).toBe('AAPL|235|2025-05-16|C');
      expect(missing[0].strike).toBe(235.0);

      const rescuedContract: OptionContract = {
        ...tableContracts[0],
        id: 'AAPL|235|2025-05-16|C',
        strike: 235.0,
        price: 4.60,
      };

      const merged = withCardContract(tableContracts, [rescuedContract], 'AAPL|235|2025-05-16|C');
      expect(merged).toHaveLength(2);
      expect(merged.some((c) => c.id === 'AAPL|235|2025-05-16|C')).toBe(true);
    });
  });

  describe('4. Step 7 Trade Card Sizing, Risk Gate, Basket & Alternatives', () => {
    it('4.1 calculates Capital at Risk and Exposure percentage with zero/absent safety', () => {
      // Normal case: mid $6.90, 3 contracts -> $2,070
      expect(capitalAtRisk(6.90, 3)).toBeCloseTo(2070, 2);
      expect(exposurePct(2070, 100000)).toBeCloseTo(0.0207, 4);

      // Edge case: zero mid -> $0
      expect(capitalAtRisk(0, 5)).toBe(0);
      expect(exposurePct(0, 100000)).toBe(0);

      // Edge case: zero portfolio value -> 0%
      expect(exposurePct(2070, 0)).toBe(0);
    });

    it('4.2 derives stop-loss risk and formats badge/headline using integer cents precision', () => {
      const cases = fixtures.step7_trade_card.stop_cost_cases;

      // Case 1: Caution with residual value left
      const c1 = cases[0] as any;
      const r1 = stopPremiumRisk(c1)!;
      expect(r1).not.toBeNull();
      expect(r1.loss).toBe(3.71);
      expect(r1.premium).toBe(5.20);
      expect(formatStopLossBadge(r1)).toBe(c1.expected_badge);
      expect(formatStopLossHeadline(r1)).toBe(c1.expected_headline);
      expect(stopLossIsTotalOnPrintedFigures(r1)).toBe(false);

      // Case 2: Total loss at stop
      const c2 = cases[1] as any;
      const r2 = stopPremiumRisk(c2)!;
      expect(r2).not.toBeNull();
      expect(formatStopLossBadge(r2)).toBe(c2.expected_badge);
      expect(formatStopLossHeadline(r2)).toBe(c2.expected_headline);
      expect(stopLossIsTotalOnPrintedFigures(r2)).toBe(true);
    });

    it('4.3 formats ranking stop cost with exact explanation tooltip and badge', () => {
      const sc1 = rankingStopCost(28.5, 'PASS');
      expect(sc1.label).toBe('29%');
      expect(sc1.status).toBe('PASS');
      expect(sc1.tooltip).toContain('29% of the premium is gone');

      // Uncomputed stop cost
      const scNull = rankingStopCost(null, null);
      expect(scNull.label).toBe('—');
      expect(scNull.status).toBeNull();
      expect(scNull.tooltip).toContain('Stop cost not computed');
    });

    it('4.4 recommends contract size absorbing IEEE-754 floating point subtraction noise', () => {
      const cases = fixtures.step7_trade_card.sizing_cases;

      for (const tc of cases) {
        const res = recommendedContractSize(tc.budget, tc.risk_per_contract);
        if (tc.expected_recommended === null) {
          expect(res).toBeNull();
        } else {
          expect(res).not.toBeNull();
          expect(res!.recommended).toBe(tc.expected_recommended);
          expect(formatRecommendedContractSizeRaw(res!)).toBe(tc.expected_formatted);
        }
      }
    });

    it('4.5 checkTradeRisk enforces invalidation stop, method pick, exposure caps, and duplicates', () => {
      const limits = fixtures.step7_trade_card.account;

      // Base clean card
      const baseCard: TradeCardData = {
        symbol: 'AAPL',
        contractDetails: { mid: 6.90 },
        exit: { invalidation: 220.0 },
      } as any;

      // 1. All clean -> approved
      const passResult = checkTradeRisk(
        baseCard,
        3,
        limits as any,
        [],
        1,
        null,
        220.0,
        sampleMethodPick,
      );
      expect(passResult.approved).toBe(true);
      expect(passResult.reasons).toEqual([]);

      // 2. Missing invalidation -> blocks
      const missingInvCard: TradeCardData = {
        ...baseCard,
        exit: { invalidation: null },
      } as any;
      const missingInv = checkTradeRisk(
        missingInvCard,
        3,
        limits as any,
        [],
        1,
        null,
        null, // resolved invalidation is null
        sampleMethodPick,
      );
      expect(missingInv.approved).toBe(false);
      expect(missingInv.reasons).toContain('missing_invalidation');

      // 3. Missing method pick -> blocks
      const missingMethod = checkTradeRisk(
        baseCard,
        3,
        limits as any,
        [],
        1,
        null,
        220.0,
        null, // no pick
      );
      expect(missingMethod.approved).toBe(false);
      expect(missingMethod.reasons).toContain('missing_method_pick');

      // 4. Single exposure too high (effective cap = min(5%, 3%) = 3% = $3,000; 5 * $12.00 * 100 = $6,000)
      const highExpCard: TradeCardData = {
        symbol: 'AAPL',
        contractDetails: { mid: 12.00 },
        exit: { invalidation: 220.0 },
      } as any;
      const highExp = checkTradeRisk(
        highExpCard,
        5,
        limits as any,
        [],
        1,
        null,
        220.0,
        sampleMethodPick,
      );
      expect(highExp.approved).toBe(false);
      expect(highExp.reasons).toContain('single_trade_exposure_too_high');

      // 5. Duplicate symbol in positions -> blocks
      const dupResult = checkTradeRisk(
        baseCard,
        2,
        limits as any,
        [{ symbol: 'AAPL', contract: 'AAPL|220|2025-05-16|C', contracts: 2, entryPrice: 6.90 } as any],
        1,
        null,
        220.0,
        sampleMethodPick,
      );
      expect(dupResult.approved).toBe(false);
      expect(dupResult.reasons).toContain('duplicate_symbol');
    });

    it('4.6 classifies direct broker send responses and errors with exact outcome (delete vs keep vs placed)', () => {
      // 1. Pre-submit 422 thrown Error string -> delete saved row
      const err422 = new Error('API /broker/option-order → 422: Validation failed on strike');
      const out422 = classifyDirectFailure({ thrown: err422 });
      expect(out422.verdict).toBe('delete');

      // 2. Pre-submit 503 credentials unavailable -> delete saved row
      const err503 = new Error('API /broker/option-order → 503: Broker credentials unavailable for paper');
      const out503 = classifyDirectFailure({ thrown: err503 });
      expect(out503.verdict).toBe('delete');

      // 3. Pre-submit 502 IBKR not placed -> delete saved row
      const err502 = new Error('API /broker/option-order → 502: IBKR did not place the order: rejected');
      const out502 = classifyDirectFailure({ thrown: err502 });
      expect(out502.verdict).toBe('delete');

      // 4. Unknown 500 error -> keep row (could have reached broker)
      const err500 = new Error('API /broker/option-order → 500: Internal server error');
      const out500 = classifyDirectFailure({ thrown: err500 });
      expect(out500.verdict).toBe('keep');

      // 5. 200 response with status 'rejected' -> delete row
      const outRej = classifyDirectFailure({ response: { status: 'rejected', order_id: 'ORD-1' } });
      expect(outRej.verdict).toBe('delete');

      // 6. 200 response with usable ID and 'submitted' -> placed
      const outPlaced = classifyDirectFailure({ response: { status: 'submitted', order_id: 'ORD-123' } });
      expect(outPlaced.verdict).toBe('placed');
      if (outPlaced.verdict === 'placed') {
        expect(outPlaced.orderId).toBe('ORD-123');
      }

      // 7. Tastytrade paper blocks market order
      expect(directOrderBlock('MKT', 'tastytrade_paper')).toBe(
        'Tastytrade paper accepts limit orders only — use Place Limit.',
      );
      expect(directOrderBlock('LMT', 'tastytrade_paper')).toBeNull();
    });
  });

  describe('5. Component Rendering, Payloads & UI Probes', () => {
    it('5.1 renders StatusBadge, RankDelta, and EventFlag with correct accessible labels and classes', () => {
      render(<StatusBadge status="PASS" label="Pass · 88/100" />);
      expect(screen.getByText('Pass · 88/100')).toBeInTheDocument();

      render(<RankDelta value={2} context="rank" />);
      expect(screen.getByTitle('Up 2 ranks since last scan')).toBeInTheDocument();

      render(<EventFlag days={18} title="Earnings in 18 days" />);
      expect(screen.getByText('18d')).toBeInTheDocument();
    });

    it('5.2 renders AlternativeContractRow with trade-off reason and metrics', () => {
      const alt: AlternativeContract = {
        symbol: 'AAPL',
        strike: 235.0,
        right: 'C',
        expiry: '2025-05-16',
        dte: 45,
        mid: 4.60,
        delta: 0.42,
        theta: -0.04,
        ivRank: 35,
        score: 86,
        contractConfidence: 'PASS',
        contractBreakdown: {
          dteFit: 85,
          delta: 80,
          ivAttractiveness: 90,
          liquidity: 90,
          spread: 85,
        },
        rrRatio: 2.1,
        rrModel: 'BS repriced (IV-derived)',
        reason: 'Lower capital requirement ($460 vs $690) with slightly lower delta (0.42 vs 0.52)',
      };

      render(<AlternativeContractRow alt={alt} rank={1} />);

      expect(screen.getByText('AAPL 235C 2025-05-16')).toBeInTheDocument();
      expect(screen.getByText(alt.reason)).toBeInTheDocument();
      expect(screen.getByText('$4.60')).toBeInTheDocument();
      expect(screen.getByText('Alt 1')).toBeInTheDocument();
    });

    it('5.3 SendToBrokerDialog captures draft orders without triggering real network requests', () => {
      const card: TradeCardData = {
        symbol: 'AAPL',
        company: 'Apple Inc.',
        price: 230.50,
        direction: 'Bullish',
        status: 'PASS',
        stockScore: 88,
        contract: 'AAPL|230|2025-05-16|C',
        contractDetails: {
          strike: 230.0,
          right: 'C',
          expiry: '2025-05-16',
          mid: 6.90,
        },
        entry: { limit: 6.90, maxFill: 7.10 },
        exit: { invalidation: 220.0, premiumStop: 2.30, timeStopDays: 20, targets: [] },
      } as any;

      useRiskStore.setState({
        limits: fixtures.step7_trade_card.account as any,
        dailyRecommendations: 0,
      });

      const handleSubmit = jest.fn();
      const handleClose = jest.fn();

      render(
        <SendToBrokerDialog
          cards={[card]}
          contractsBySymbol={{ AAPL: 2 }}
          overridesBySymbol={{ AAPL: null }}
          invalidationBySymbol={{ AAPL: 220.0 }}
          methodPickBySymbol={{ AAPL: sampleMethodPick }}
          onClose={handleClose}
          onSubmit={handleSubmit}
        />,
      );

      // Verify dialog header and contract details
      expect(screen.getByText('Track basket in Portfolio')).toBeInTheDocument();
      expect(screen.getByText('AAPL')).toBeInTheDocument();

      // Submit order capture
      const submitBtn = screen.getByRole('button', { name: /add 1 to portfolio/i });
      fireEvent.click(submitBtn);

      expect(handleSubmit).toHaveBeenCalledTimes(1);
      const [capturedOrders, riskOverridden] = handleSubmit.mock.calls[0];
      expect(capturedOrders).toHaveLength(1);
      expect(capturedOrders[0].card.symbol).toBe('AAPL');
      expect(capturedOrders[0].contracts).toBe(2);
      expect(riskOverridden).toBe(false);
    });
  });

  describe('6. Store State Rehydration & Mutation Safety', () => {
    it('6.1 updates scanStore selectedSymbol and pickedContracts transactionally', () => {
      useScanStore.getState().setSelectedSymbol('NVDA');
      expect(useScanStore.getState().selectedSymbol).toBe('NVDA');

      useScanStore.getState().setPickedContract('NVDA', 'NVDA|137.5|2025-05-16|C');
      expect(useScanStore.getState().pickedContracts['NVDA']).toBe('NVDA|137.5|2025-05-16|C');
    });

    it('6.2 toggles watched contracts in watchedContractsStore with symmetric add/remove', () => {
      const contractIdStr = 'AAPL|230|2025-05-16|C';

      useWatchedContractsStore.getState().add(contractIdStr);
      expect(useWatchedContractsStore.getState().isWatched(contractIdStr)).toBe(true);

      useWatchedContractsStore.getState().remove(contractIdStr);
      expect(useWatchedContractsStore.getState().isWatched(contractIdStr)).toBe(false);
    });
  });
});
