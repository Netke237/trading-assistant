'use client';
import { useEffect, useRef, useState, useCallback, useMemo } from 'react';
import { useSearchParams } from 'next/navigation';
import { api } from '@/lib/api';
import { useChartStore, type IndicatorConfig, type Interval, type ChartType } from '@/lib/chartStore';
import { ChartWSClient, type WSMessage, type ConnectionState } from '@/lib/chartWS';
import { calcEMA, calcSMA, calcRSI, calcMACD, calcBB, calcATR, calcVWAP, type Candle, type Point } from '@/lib/indicators';
import { calcAnchoredVWAP, calcKeyLevels, calcCrossSignals, calcSignalMarkers, calcVolumeProfile, resample } from '@/lib/chart/overlays';
import { VolumeProfilePrimitive } from '@/lib/chartPrimitives/VolumeProfilePrimitive';
import { PreviewPrimitive } from '@/lib/chartPrimitives/PreviewPrimitive';
import MtfDashboard from '@/components/organisms/MtfDashboard';
import { buildMtfRow } from '@/lib/chart/mtf';
import type { MtfRow } from '@/types/overlays';
import { useStructureStore } from '@/lib/structureStore';
import type { StructureSignal } from '@/types/structure';
import { useChartAlertStore } from '@/lib/chartAlertStore';
import { evaluateRules, type RegimeSnapshot } from '@/lib/chartAlertEngine';
import AlertRuleBuilder from '@/components/organisms/AlertRuleBuilder';
import AlertToast from '@/components/organisms/AlertToast';
import ChartClickPopover from '@/components/molecules/ChartClickPopover';
import TextInputPopover from '@/components/molecules/TextInputPopover';
import type { SeriesConfig } from '@/components/organisms/ChartPane';
import ChartPane from '@/components/organisms/ChartPane';
import ChartTopBar from '@/components/organisms/ChartTopBar';
import DrawingToolbar, { type DrawingTool } from '@/components/organisms/DrawingToolbar';
import IndicatorPanel from '@/components/organisms/IndicatorPanel';
import StructurePanel from '@/components/organisms/StructurePanel';
import { ChartOverlays } from '@/components/organisms/ChartOverlays';
import DrawingOverlays from '@/components/organisms/DrawingOverlays';
import ChartRightPanel, { type DataValues } from '@/components/organisms/ChartRightPanel';
import { useDrawingStore } from '@/lib/drawingStore';
import { hitTestDrawing, type Handle } from '@/lib/chart/hitTest';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { buildPaperStockPosition } from '@/lib/paperTrade';
import type { DrawingPoint, Drawing } from '@/types/overlays';
import type { IChartApi, ISeriesApi, MouseEventParams } from 'lightweight-charts';
import { HistogramSeries, createSeriesMarkers, type Time, type ISeriesMarkersPluginApi } from 'lightweight-charts';
import styles from './ChartWorkspace.module.css';

// ── Indicator computation helpers ─────────────────────────────────────────────

function buildMainSeries(candles: Candle[], indicators: IndicatorConfig[], chartType: ChartType, interval: Interval): SeriesConfig[] {
  const mainType: SeriesConfig['type'] =
    chartType === 'bar'  ? 'Bar'  :
    chartType === 'line' ? 'Line' :
    'Candlestick';

  const mainData: SeriesConfig['data'] = chartType === 'line'
    ? candles.map(c => ({ time: c.time, value: c.close } as Point))
    : candles;

  const series: SeriesConfig[] = [
    { id: `candles-${chartType}`, type: mainType, data: mainData },
  ];
  for (const ind of indicators) {
    if (ind.pane !== 'main') continue;
    if (ind.type === 'EMA')  series.push({ id: ind.id, type: 'Line', data: calcEMA(candles, ind.params.period ?? 20), color: ind.color });
    if (ind.type === 'SMA')  series.push({ id: ind.id, type: 'Line', data: calcSMA(candles, ind.params.period ?? 20), color: ind.color });
    if (ind.type === 'VWAP' && interval !== '1D' && interval !== '1W') {
      series.push({ id: ind.id, type: 'Line', data: calcVWAP(candles), color: ind.color });
    }
    if (ind.type === 'BB') {
      const bb = calcBB(candles, ind.params.period ?? 20, ind.params.stdDev ?? 2);
      series.push({ id: `${ind.id}-upper`, type: 'Line', data: bb.upper,  color: '#4caf50' }); // green
      series.push({ id: `${ind.id}-mid`,   type: 'Line', data: bb.middle, color: '#2196f3' }); // blue
      series.push({ id: `${ind.id}-lower`, type: 'Line', data: bb.lower,  color: '#f44336' }); // red
    }
    if (ind.type === 'MASUITE') {
      const lens = [ind.params.ma1, ind.params.ma2, ind.params.ma3, ind.params.ma4].filter((n) => n && n > 0);
      const cols = ['#4f8ef7', '#e0a030', '#e0e040', '#e040e0'];
      lens.forEach((len, i) => series.push({ id: `${ind.id}-ma${i}`, type: 'Line', data: calcEMA(candles, len), color: cols[i] }));
    }
    if (ind.type === 'AVWAP') {
      series.push({ id: ind.id, type: 'Line', data: calcAnchoredVWAP(candles, ind.params.anchorMs), color: ind.color });
    }
    if (ind.type === 'KEYLEVELS') {
      const lv = calcKeyLevels(candles, interval);
      const flat = (v: number | null): Point[] => v == null ? [] : candles.map((c) => ({ time: c.time, value: v }));
      if (ind.params.day)  { series.push({ id: `${ind.id}-pdh`, type: 'Line', data: flat(lv.pdh), color: '#808080' }); series.push({ id: `${ind.id}-pdl`, type: 'Line', data: flat(lv.pdl), color: '#808080' }); }
      if (ind.params.week) { series.push({ id: `${ind.id}-pwh`, type: 'Line', data: flat(lv.pwh), color: '#4a90a4' }); series.push({ id: `${ind.id}-pwl`, type: 'Line', data: flat(lv.pwl), color: '#4a90a4' }); }
    }
    if (ind.type === 'HTFLEVELS') {
      const htf = resample(candles, ind.params.tfMin || 240);
      const lastBar = htf[htf.length - 1];
      const flatN = (v: number | undefined): Point[] => v == null ? [] : candles.map((c) => ({ time: c.time, value: v }));
      series.push({ id: `${ind.id}-hh`, type: 'Line', data: flatN(lastBar?.high), color: '#30a060' });
      series.push({ id: `${ind.id}-hl`, type: 'Line', data: flatN(lastBar?.low),  color: '#c04040' });
      series.push({ id: `${ind.id}-hc`, type: 'Line', data: flatN(lastBar?.close), color: '#808080' });
    }
  }
  return series;
}

function buildIndicatorLabels(indicators: IndicatorConfig[]): Record<string, string> {
  const labels: Record<string, string> = {};
  for (const ind of indicators) {
    const period = ind.params?.period;
    const p = period ? `(${period})` : '';
    if (ind.type === 'SMA')  labels[ind.id] = `SMA${p}`;
    if (ind.type === 'EMA')  labels[ind.id] = `EMA${p}`;
    if (ind.type === 'VWAP') labels[ind.id] = 'VWAP';
    if (ind.type === 'RSI')  labels[ind.id] = `RSI${p}`;
    if (ind.type === 'ATR')  labels[ind.id] = `ATR${p}`;
    if (ind.type === 'BB') {
      labels[`${ind.id}-upper`] = 'BB Upper';
      labels[`${ind.id}-mid`]   = 'BB Mid';
      labels[`${ind.id}-lower`] = 'BB Lower';
    }
    if (ind.type === 'MACD') {
      labels[`${ind.id}-line`] = 'MACD';
      labels[`${ind.id}-sig`]  = 'Signal';
      labels[`${ind.id}-hist`] = 'Histogram';
    }
    if (ind.type === 'VOL') labels[`${ind.id}-vol`] = 'Volume';
    // candle series id
    labels[`candles-${ind.type}`] = 'Close'; // fallback for candles
  }
  return labels;
}

function buildSubSeries(candles: Candle[], ind: IndicatorConfig): SeriesConfig[] {
  if (ind.type === 'VOL')  return [{ id: `${ind.id}-vol`,  type: 'Histogram', data: candles.map(c => ({ time: c.time, value: c.volume })), color: ind.color }];
  if (ind.type === 'RSI')  return [{ id: `${ind.id}-rsi`,  type: 'Line',      data: calcRSI(candles, ind.params.period ?? 14), color: ind.color }];
  if (ind.type === 'ATR')  return [{ id: `${ind.id}-atr`,  type: 'Line',      data: calcATR(candles, ind.params.period ?? 14), color: ind.color }];
  if (ind.type === 'MACD') {
    const m = calcMACD(candles, ind.params.fast ?? 12, ind.params.slow ?? 26, ind.params.signal ?? 9);
    return [
      { id: `${ind.id}-line`, type: 'Line',      data: m.macd,      color: ind.color },
      { id: `${ind.id}-sig`,  type: 'Line',      data: m.signal,    color: '#e0a030' },
      { id: `${ind.id}-hist`, type: 'Histogram', data: m.histogram, color: '#4a4a6a' },
    ];
  }
  return [];
}


function getIndicatorPoints(candles: Candle[], indicators: IndicatorConfig[]): Record<string, Point[]> {
  const result: Record<string, Point[]> = {};
  for (const ind of indicators) {
    if (ind.type === 'EMA')  result[ind.id] = calcEMA(candles, ind.params.period ?? 20).map(p => ({ time: p.time, value: p.value }));
    if (ind.type === 'SMA')  result[ind.id] = calcSMA(candles, ind.params.period ?? 20).map(p => ({ time: p.time, value: p.value }));
    if (ind.type === 'RSI')  result[ind.id] = calcRSI(candles, ind.params.period ?? 14).map(p => ({ time: p.time, value: p.value }));
    if (ind.type === 'ATR')  result[ind.id] = calcATR(candles, ind.params.period ?? 14).map(p => ({ time: p.time, value: p.value }));
    if (ind.type === 'MACD') {
      const m = calcMACD(candles, ind.params.fast ?? 12, ind.params.slow ?? 26, ind.params.signal ?? 9);
      result[ind.id] = m.macd.map(p => ({ time: p.time, value: p.value }));
    }
  }
  return result;
}

// ── Component ─────────────────────────────────────────────────────────────────

const NO_SIGNALS: StructureSignal[] = [];

const rid = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 6);

export default function ChartWorkspace() {
  const params = useSearchParams();
  const { symbol, interval, chartType, activeIndicators, setSymbol, setInterval } = useChartStore();
  const [candles, setCandles] = useState<Candle[]>([]);
  const [drawingTool, setDrawingTool] = useState<DrawingTool>('cursor');
  const [drawingColor, setDrawingColor] = useState('#dddddd');
  const drawingColorRef = useRef('#dddddd');
  useEffect(() => { drawingColorRef.current = drawingColor; }, [drawingColor]);
  const [showIndicators, setShowIndicators] = useState(false);
  const [showStructure, setShowStructure] = useState(false);
  const [showAlerts, setShowAlerts] = useState(false);
  const [clickPopover, setClickPopover] = useState<{ kind: 'alert' | 'buy'; price: number; time: number } | null>(null);
  const [textDraft, setTextDraft] = useState<{ time: number; price: number; editId?: string } | null>(null);
  const [prefillPrice, setPrefillPrice] = useState<number | null>(null);
  const [buyQty, setBuyQty] = useState(1);
  const [crosshair, setCrosshair] = useState<DataValues>({ time: null, indicators: {} });
  const [connState, setConnState] = useState<ConnectionState>('connecting');
  const [chartApi, setChartApi] = useState<IChartApi | null>(null);
  const [mainSeries, setMainSeries] = useState<ISeriesApi<'Candlestick'> | null>(null);
  const [showRegime, setShowRegime] = useState(false);
  const [regimeModel, setRegimeModel] = useState<'OMM' | 'HMM'>('OMM');
  const regimeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const regimeDataRef = useRef<Array<{ time: string; state: string }>>([]);
  const [wsError, setWsError] = useState<string | null>(null);
  const wsRef = useRef<ChartWSClient | null>(null);
  const chartApiRef = useRef<IChartApi | null>(null);
  const mainSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const handleSeriesReady = useCallback(
    (chart: IChartApi, series: ISeriesApi<'Candlestick'>) => {
      chartApiRef.current = chart;
      mainSeriesRef.current = series;
      setChartApi(chart);
      setMainSeries(series);
    },
    // chartApiRef and mainSeriesRef are stable refs — no deps needed
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );
  const vpPrimRef = useRef<VolumeProfilePrimitive | null>(null);
  const previewRef = useRef<PreviewPrimitive | null>(null);
  const markersApiRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const pendingPtsRef = useRef<DrawingPoint[]>([]);

  interface DragState {
    id: string;
    handle: Handle;
    startDrawing: Drawing;
    startX: number;
    startY: number;
    lastUpdateMs?: number;
  }
  const dragRef = useRef<DragState | null>(null);
  // Tracks whether the last pointer-down resulted in a drag (pointer moved > 4px).
  // Used to suppress the text-edit popover when the user drags a drawing instead of clicking it.
  const wasDragRef = useRef(false);

  const drawings = useDrawingStore((s) => s.drawings);
  const addDrawing = useDrawingStore((s) => s.addDrawing);
  const removeDrawing = useDrawingStore((s) => s.removeDrawing);
  const updateDrawing = useDrawingStore((s) => s.updateDrawing);
  const clearForSymbol = useDrawingStore((s) => s.clearForSymbol);

  const updateDrawingRef = useRef(updateDrawing);
  useEffect(() => { updateDrawingRef.current = updateDrawing; }, [updateDrawing]);

  const structureVisible = useStructureStore((s) => s.structureVisible);
  const structureVisibility = useStructureStore((s) => s.visibility);

  // Map UI interval to backend interval for WS + store key consistency
  const backendInterval =
    interval === '1D' ? 'daily' :
    interval === '1W' ? 'weekly' :
    interval;

  const structureSignals = useStructureStore((s) => s.signals[`${symbol}:${backendInterval}`] ?? NO_SIGNALS);

  // Deep-link: read ?symbol= and ?interval= query params once on mount
  useEffect(() => {
    const sym = params?.get('symbol');
    const iv  = params?.get('interval');
    if (sym) setSymbol(sym.toUpperCase());
    if (iv)  setInterval(iv as Interval);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // intentionally run only once on mount

  // Keyed on mainSeries identity — re-attaches correctly when chart type switches
  // (Candlestick → Line/Bar creates a new series object and fires onSeriesReady again).
  useEffect(() => {
    if (!mainSeries) return;
    const prim = new PreviewPrimitive();
    mainSeries.attachPrimitive(prim);
    previewRef.current = prim;
    return () => {
      try { mainSeries.detachPrimitive(prim); } catch { /* ignore */ }
      previewRef.current = null;
    };
  }, [mainSeries]);

  // Sync alert rules from backend on mount
  useEffect(() => {
    useChartAlertStore.getState().syncRules();
  }, []);

  // Sync drawings from backend when symbol/interval change
  useEffect(() => {
    useDrawingStore.getState().syncFromBackend(symbol, interval);
  }, [symbol, interval]);

  // On intraday charts the model toggle is irrelevant — always use intraday HMM.
  // Using effectiveRegimeModel in the dep array prevents a pointless re-fetch+flash
  // when the user clicks OMM↔HMM while viewing a sub-daily interval.
  const effectiveRegimeModel = interval !== '1D' && interval !== '1W' ? 'HMM' : regimeModel;

  // Regime background overlay
  useEffect(() => {
    const chart = chartApi;
    if (!chart) return;

    if (regimeSeriesRef.current) {
      try { chart.removeSeries(regimeSeriesRef.current); } catch { /* already removed */ }
      regimeSeriesRef.current = null;
    }

    if (!showRegime) {
      regimeDataRef.current = [];
      return;
    }

    let cancelled = false;
    const isIntraday = interval !== '1D' && interval !== '1W';

    const STATE_COLOR: Record<string, string> = {
      // OMM + daily directional HMM states
      Bull:             'rgba(38,166,154,0.18)',
      Bear:             'rgba(239,83,80,0.18)',
      Choppy:           'rgba(251,192,45,0.12)',
      Sideways:         'rgba(251,192,45,0.12)',
      // Intraday HMM states
      Trending:         'rgba(38,166,154,0.18)',
      'Mean-reverting': 'rgba(120,86,210,0.14)',
    };

    async function loadRegime() {
      try {
        const rawData: Array<{ time: string; state: string }> = isIntraday
          ? await api.getIntradayRegimeSeries(symbol, interval)
          : await api.getRegimeSeries(symbol, undefined, effectiveRegimeModel);

        if (cancelled || !chart) return;

        regimeDataRef.current = rawData;

        const rs = chart.addSeries(HistogramSeries, {
          priceScaleId: 'regime',
          lastValueVisible: false,
          priceLineVisible: false,
          color: 'rgba(128,128,128,0.1)',
        }, 0);

        chart.priceScale('regime').applyOptions({
          visible: false,
          scaleMargins: { top: 0, bottom: 0 },
        });

        rs.setData(rawData.map(d => ({
          time: d.time as Time,
          value: 1,
          color: STATE_COLOR[d.state] ?? 'rgba(128,128,128,0.10)',
        })));

        regimeSeriesRef.current = rs;
      } catch {
        // regime data unavailable — silent fail
      }
    }

    loadRegime();
    return () => {
      cancelled = true;
      // Remove the series on cleanup (effect re-run or unmount)
      if (regimeSeriesRef.current) {
        try { chart.removeSeries(regimeSeriesRef.current); } catch { /* chart may already be destroyed */ }
        regimeSeriesRef.current = null;
      }
    };
  }, [showRegime, effectiveRegimeModel, symbol, interval, chartApi]);

  // Connect/reconnect WebSocket when symbol or interval changes
  useEffect(() => {
    wsRef.current?.destroy();

    const client = new ChartWSClient(symbol, backendInterval);
    client.onStateChange(setConnState);
    const unsubscribe = client.onMessage((msg: WSMessage) => {
      if (msg.type === 'history') {
        setCandles(msg.candles);
        setWsError(null);
      }
      if (msg.type === 'error') {
        setWsError(msg.message ?? 'Connection error');
      }
      if (msg.type === 'tick') {
        setCandles(prev => {
          if (!prev.length) return prev;
          const last = prev[prev.length - 1];
          if (last.time === msg.data.timestamp) {
            return [
              ...prev.slice(0, -1),
              { ...last, close: msg.data.price, high: Math.max(last.high, msg.data.price), low: Math.min(last.low, msg.data.price), volume: last.volume + msg.data.volume },
            ];
          }
          return [...prev, { time: msg.data.timestamp, open: msg.data.price, high: msg.data.price, low: msg.data.price, close: msg.data.price, volume: msg.data.volume }];
        });
      }
      if (msg.type === 'structure') {
        const key = `${msg.symbol}:${msg.interval}`;
        useStructureStore.getState().setSignals(key, msg.signals);
      }
      if (msg.type === 'alert_triggered') {
        // skipApiSync=true: backend already persisted this entry and sent
        // email/telegram notifications. Re-posting would create a duplicate
        // DB row and fire double notifications.
        useChartAlertStore.getState().addHistory(msg.entry, true);
        useChartAlertStore.getState().updateRule(msg.entry.rule_id, {
          last_triggered_at: msg.entry.triggered_at,
        });
        useChartAlertStore.getState().pushToast({
          id: msg.entry.id,
          message: `${msg.entry.symbol} \u00b7 ${msg.entry.reason}`,
          timestamp: Date.now(),
        });
      }
    });
    client.connect();
    wsRef.current = client;

    return () => {
      unsubscribe();
      client.destroy();
    };
  }, [symbol, interval]);

  // Alert evaluation on candle-close
  const prevCandleCount = useRef(candles.length);
  useEffect(() => {
    if (candles.length > prevCandleCount.current && prevCandleCount.current > 0) {
      const closedCandle = candles[prevCandleCount.current - 1];
      const alertRules = useChartAlertStore.getState().rules.filter(
        r => r.symbol === symbol && r.interval === interval
      );
      if (alertRules.length > 0) {
        const indicatorPoints = getIndicatorPoints(candles, activeIndicators);
        const regimeEntry = regimeDataRef.current.find(
          (d) => d.time === String(closedCandle.time),
        );
        const _isIntraday = interval !== '1D' && interval !== '1W';
        const currentRegime: RegimeSnapshot | null = regimeEntry
          ? { state: regimeEntry.state, model: _isIntraday ? 'HMM' : regimeModel }
          : null;
        const triggered = evaluateRules(
          alertRules,
          closedCandle,
          candles,
          indicatorPoints,
          structureSignals,
          new Date(),
          symbol,
          interval,
          currentRegime,
        );
        for (const history of triggered) {
          useChartAlertStore.getState().addHistory(history);
          useChartAlertStore.getState().updateRule(history.rule_id, {
            last_triggered_at: history.triggered_at,
          });
          useChartAlertStore.getState().pushToast({
            id: history.id,
            message: `${history.symbol} · ${history.reason}`,
            timestamp: Date.now(),
          });
        }
      }
    }
    prevCandleCount.current = candles.length;
  }, [candles.length, symbol, interval, activeIndicators, structureSignals]);

  const candlesRef = useRef(candles);
  useEffect(() => { candlesRef.current = candles; }, [candles]);

  const handleCrosshair = useCallback((time: string | null, values: Record<string, number>) => {
    if (!time) { setCrosshair({ time: null, indicators: {} }); return; }
    const last = candlesRef.current.find(c => c.time === time);
    setCrosshair({
      time,
      open:   last?.open,
      high:   last?.high,
      low:    last?.low,
      close:  last?.close,
      volume: last?.volume,
      indicators: values,
    });
  }, []);

  const allSeries = useMemo(() => {
    const main = buildMainSeries(candles, activeIndicators, chartType, interval); // pane 0
    const subs: SeriesConfig[] = [];
    let pane = 1;
    for (const ind of activeIndicators.filter((i) => i.pane === 'sub')) {
      for (const s of buildSubSeries(candles, ind)) subs.push({ ...s, paneIndex: pane });
      pane += 1;
    }
    return [...main, ...subs];
  }, [candles, activeIndicators, chartType, interval]);

  const indicatorLabels = useMemo(
    () => buildIndicatorLabels(activeIndicators),
    [activeIndicators],
  );

  const mtfRows: MtfRow[] = useMemo(
    () => activeIndicators.some((i) => i.type === 'MTF') ? [buildMtfRow(interval, candles, 14)] : [],
    [activeIndicators, interval, candles],
  );

  // Reset markers plugin ref when series changes (chart-type switch).
  // Separate from the markers+VP effect to avoid resetting on candle ticks.
  useEffect(() => {
    markersApiRef.current = null;
  }, [mainSeries]);

  useEffect(() => {
    const series = mainSeries;
    if (!series) return;
    // markers
    const markers: { time: Time; position: 'aboveBar' | 'belowBar'; color: string; shape: 'arrowUp' | 'arrowDown'; text: string }[] = [];
    for (const ind of activeIndicators) {
      if (ind.type === 'XSIGNAL') for (const m of calcCrossSignals(candles, ind.params.emaLen, ind.params.smaLen)) markers.push({ time: m.time as Time, position: m.position, color: m.color, shape: m.shape, text: m.text });
      if (ind.type === 'SIGNALS') for (const m of calcSignalMarkers(candles, ind.params.fast, ind.params.slow, ind.params.rsi)) markers.push({ time: m.time as Time, position: m.position, color: m.color, shape: m.shape, text: m.text });
    }
    markers.sort((a, b) => Number(a.time) - Number(b.time));
    if (!markersApiRef.current) markersApiRef.current = createSeriesMarkers(series, []);
    markersApiRef.current.setMarkers(markers);
    // volume profile
    if (vpPrimRef.current) { try { series.detachPrimitive(vpPrimRef.current); } catch { /* ignore */ } vpPrimRef.current = null; }
    const vpCfg = activeIndicators.find((i) => i.type === 'VPROFILE');
    if (vpCfg) {
      const vp = calcVolumeProfile(candles, vpCfg.params.lookback, vpCfg.params.rows);
      vpPrimRef.current = new VolumeProfilePrimitive(vp);
      series.attachPrimitive(vpPrimRef.current);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [candles, activeIndicators, mainSeries]);

  // Drag-to-move drawings (cursor tool only)
  useEffect(() => {
    if (drawingTool !== 'cursor') return;
    const chart = chartApi;
    const series = mainSeries;
    if (!chart || !series) return;
    const el = chart.chartElement();

    const calcUpdatedPoints = (drag: DragState, x: number, y: number): DrawingPoint[] | null => {
      const newTime = chart.timeScale().coordinateToTime(x);
      const newPrice = series.coordinateToPrice(y);
      if (newTime == null || newPrice == null) return null;
      const startPrice0 = series.coordinateToPrice(drag.startY);
      if (startPrice0 == null) return null;
      const dp = newPrice - startPrice0;
      const { handle, startDrawing } = drag;
      // coordinateToTime returns Time (string on daily charts, number on intraday).
      // Number(string_date) = NaN which corrupts stored points. Cast directly instead.
      const asDrawingTime = (t: Time) => t as unknown as number;
      if (handle === 'p0') return [{ time: asDrawingTime(newTime), price: newPrice }, ...startDrawing.points.slice(1)];
      if (handle === 'p1') return [startDrawing.points[0], { time: asDrawingTime(newTime), price: newPrice }];
      if (handle === 'whole' && startDrawing.kind === 'hline') return startDrawing.points.map((p) => ({ time: p.time, price: p.price + dp }));
      // For whole-body move of 2-point drawings: apply pixel offset to each point's x, then snap to
      // the nearest bar. Raw timestamp arithmetic (p.time + dt) produces timestamps that don't
      // correspond to any bar when dragging across data gaps, making timeToCoordinate return null.
      const dx = x - drag.startX;
      return startDrawing.points.map((p) => {
        const origX = chart.timeScale().timeToCoordinate(p.time as unknown as Time);
        const snapTime = origX != null ? chart.timeScale().coordinateToTime(origX + dx) : null;
        return { time: snapTime != null ? asDrawingTime(snapTime) : p.time, price: p.price + dp };
      });
    };

    const toX = (t: number): number | null => {
      const coord = chart.timeScale().timeToCoordinate(t as unknown as Time);
      return coord ?? null;
    };
    const toY = (p: number): number | null => {
      const coord = series.priceToCoordinate(p);
      return coord ?? null;
    };

    const onPointerDown = (e: PointerEvent) => {
      wasDragRef.current = false;
      const rect = el.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      const candidates = useDrawingStore.getState().drawings.filter(
        (d) => d.symbol === symbol && d.interval === interval,
      );
      const hit = candidates.find((d) => hitTestDrawing(d, x, y, toX, toY, 8).hit);
      if (!hit) return;
      const result = hitTestDrawing(hit, x, y, toX, toY, 8);
      dragRef.current = {
        id: hit.id,
        handle: result.handle,
        startDrawing: { ...hit, points: hit.points.map((p) => ({ ...p })) },
        startX: x,
        startY: y,
      };
      chart.applyOptions({ handleScroll: false, handleScale: false });
      e.stopPropagation();
    };

    const onPointerMove = (e: PointerEvent) => {
      const drag = dragRef.current;
      if (!drag) return;
      const rect = el.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      if (Math.hypot(x - drag.startX, y - drag.startY) > 4) {
        wasDragRef.current = true;
      }
      const updatedPoints = calcUpdatedPoints(drag, x, y);
      if (!updatedPoints) return;
      const now = Date.now();
      if (now - (drag.lastUpdateMs ?? 0) >= 50) {
        drag.lastUpdateMs = now;
        updateDrawingRef.current(drag.id, { points: updatedPoints });
      }
    };

    const onPointerUp = (e: PointerEvent) => {
      const drag = dragRef.current;
      if (!drag) return;
      const rect = el.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      const updatedPoints = calcUpdatedPoints(drag, x, y);
      if (updatedPoints) {
        updateDrawingRef.current(drag.id, { points: updatedPoints });
      }
      dragRef.current = null;
      chart.applyOptions({ handleScroll: true, handleScale: true });
    };

    const onPointerCancel = () => {
      if (!dragRef.current) return;
      dragRef.current = null;
      chart.applyOptions({ handleScroll: true, handleScale: true });
    };

    el.addEventListener('pointerdown', onPointerDown);
    el.addEventListener('pointermove', onPointerMove);
    el.addEventListener('pointerup', onPointerUp);
    el.addEventListener('pointercancel', onPointerCancel);

    return () => {
      el.removeEventListener('pointerdown', onPointerDown);
      el.removeEventListener('pointermove', onPointerMove);
      el.removeEventListener('pointerup', onPointerUp);
      el.removeEventListener('pointercancel', onPointerCancel);
      try { chart.applyOptions({ handleScroll: true, handleScale: true }); } catch { /* chart may be destroyed on unmount */ }
      dragRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [drawingTool, symbol, interval, chartApi, mainSeries]);

  // Click-to-draw for trendline / hline / rect tools
  useEffect(() => {
    const chart = chartApi;
    const series = mainSeries;
    if (!chart || !series) return;
    if (drawingTool !== 'cursor' && drawingTool !== 'trendline' && drawingTool !== 'hline' && drawingTool !== 'rect' && drawingTool !== 'alert' && drawingTool !== 'buy' && drawingTool !== 'text' && drawingTool !== 'eraser' && drawingTool !== 'arrow' && drawingTool !== 'arrow_up' && drawingTool !== 'arrow_down' && drawingTool !== 'circle' && drawingTool !== 'path') {
      pendingPtsRef.current = [];
      // Clear any leftover preview when switching away from a drawing tool
      previewRef.current?.setState({ kind: null, origin: null, cursor: null });
      return;
    }

    // Clear preview whenever the tool changes (covers switching between trendline/rect/hline)
    previewRef.current?.setState({ kind: null, origin: null, cursor: null });
    pendingPtsRef.current = [];

    const onClick = (param: MouseEventParams<Time>) => {
      if (!param.point) return;
      const price = series.coordinateToPrice(param.point.y);
      if (price == null) return;
      const time = Number(param.time ?? 0);
      if (drawingTool === 'cursor' || drawingTool === 'text') {
        // Check if clicking (not dragging) on an existing text drawing — open popover in edit mode
        if (!wasDragRef.current) {
          const toX = (t: number): number | null => chartApi?.timeScale().timeToCoordinate(t as unknown as Time) ?? null;
          const toY = (p: number): number | null => mainSeries?.priceToCoordinate(p) ?? null;
          const textDrawings = useDrawingStore.getState().drawings.filter(
            d => d.symbol === symbol && d.interval === interval && d.kind === 'text',
          );
          const hitText = textDrawings.find(d => hitTestDrawing(d, param.point!.x, param.point!.y, toX, toY, 8).hit);
          if (hitText) {
            setTextDraft({ time: hitText.points[0].time, price: hitText.points[0].price, editId: hitText.id });
            return;
          }
        }
        // For cursor tool: do nothing further (drag handles moves)
        if (drawingTool === 'cursor') return;
        // For text tool: fall through to create a new annotation
      }
      if (drawingTool === 'eraser') {
        const toX = (t: number): number | null => chartApi?.timeScale().timeToCoordinate(t as unknown as Time) ?? null;
        const toY = (p: number): number | null => mainSeries?.priceToCoordinate(p) ?? null;
        const eraserDrawings = useDrawingStore.getState().drawings.filter(d => d.symbol === symbol && d.interval === interval);
        const hit = eraserDrawings.find(d => hitTestDrawing(d, param.point!.x, param.point!.y, toX, toY, 6).hit);
        if (hit) removeDrawing(hit.id);
        return;
      }
      if (drawingTool === 'alert') { setClickPopover({ kind: 'alert', price, time }); return; }
      if (drawingTool === 'buy') { setClickPopover({ kind: 'buy', price, time }); return; }
      if (drawingTool === 'text') { setTextDraft({ time, price }); return; }
      if (drawingTool === 'arrow_up') {
        addDrawing({ id: rid(), symbol, interval, kind: 'arrow_up', points: [{ time, price }], color: drawingColorRef.current, width: 1, createdAt: new Date().toISOString() });
        return;
      }
      if (drawingTool === 'arrow_down') {
        addDrawing({ id: rid(), symbol, interval, kind: 'arrow_down', points: [{ time, price }], color: drawingColorRef.current, width: 1, createdAt: new Date().toISOString() });
        return;
      }
      if (drawingTool === 'hline') {
        addDrawing({ id: rid(), symbol, interval, kind: 'hline', points: [{ time, price }], color: drawingColorRef.current, width: 1, createdAt: new Date().toISOString() });
        return;
      }
      // 2-point tools: ignore clicks in chart whitespace (no time → off-screen endpoint at epoch 0)
      if ((drawingTool === 'trendline' || drawingTool === 'rect' || drawingTool === 'arrow' || drawingTool === 'circle' || drawingTool === 'path') && param.time == null) return;
      pendingPtsRef.current.push({ time, price });
      if (pendingPtsRef.current.length === 1) {
        // First point recorded — show origin marker
        previewRef.current?.setState({
          kind: (drawingTool === 'arrow' || drawingTool === 'trendline' || drawingTool === 'circle')
            ? drawingTool as 'trendline' | 'arrow' | 'circle'
            : drawingTool === 'path'
            ? 'trendline'
            : 'rect',
          origin: { x: param.point.x, y: param.point.y },
          cursor: null,
        });
      } else if (pendingPtsRef.current.length === 2) {
        if (drawingTool === 'path') {
          previewRef.current?.setState({
            kind: 'trendline',
            origin: { x: param.point.x, y: param.point.y },
            cursor: null,
          });
        } else {
          previewRef.current?.setState({ kind: null, origin: null, cursor: null });
          const kind = drawingTool as 'trendline' | 'rect' | 'arrow' | 'circle';
          addDrawing({ id: rid(), symbol, interval, kind, points: [...pendingPtsRef.current], color: drawingColorRef.current, width: 1, createdAt: new Date().toISOString() });
          pendingPtsRef.current = [];
        }
      } else if (pendingPtsRef.current.length > 2 && drawingTool === 'path') {
        previewRef.current?.setState({
          kind: 'trendline',
          origin: { x: param.point.x, y: param.point.y },
          cursor: null,
        });
      }
    };
    chart.subscribeClick(onClick);

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && drawingTool === 'path') {
        pendingPtsRef.current = [];
        previewRef.current?.setState({ kind: null, origin: null, cursor: null });
      }
    };
    window.addEventListener('keydown', onKeyDown);

    // Crosshair subscription — active only while a first point is pending
    const onCrosshair = (param: MouseEventParams<Time>) => {
      if (pendingPtsRef.current.length !== 1) return;
      previewRef.current?.setState({
        ...previewRef.current.state,
        cursor: param.point ? { x: param.point.x, y: param.point.y } : null,
      });
    };
    chart.subscribeCrosshairMove(onCrosshair);

    return () => {
      chart.unsubscribeClick(onClick);
      chart.unsubscribeCrosshairMove(onCrosshair);
      window.removeEventListener('keydown', onKeyDown);
      if (drawingTool === 'path' && pendingPtsRef.current.length >= 2) {
        addDrawing({
          id: rid(), symbol, interval, kind: 'path',
          points: [...pendingPtsRef.current],
          color: drawingColorRef.current,
          width: 1,
          createdAt: new Date().toISOString(),
        });
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [drawingTool, symbol, interval, chartApi, mainSeries]);

  return (
    <div className={styles.workspace}>
      <ChartTopBar
        onToggleIndicators={() => setShowIndicators(v => !v)}
        onToggleStructure={() => setShowStructure(v => !v)}
        onToggleAlerts={() => setShowAlerts(v => !v)}
        onToggleRegime={() => setShowRegime(v => !v)}
        showRegime={showRegime}
        regimeModel={regimeModel}
        onSetRegimeModel={setRegimeModel}
        connState={connState}
        wsError={wsError}
      />
      {showIndicators && <IndicatorPanel onClose={() => setShowIndicators(false)} />}
      <div className={styles.body}>
        <DrawingToolbar active={drawingTool} onChange={setDrawingTool} onClear={() => { clearForSymbol(symbol, interval); }} color={drawingColor} onColorChange={setDrawingColor} />
        <div className={styles.charts}>
          <div className={styles.mainPane}>
            <ChartPane
              series={allSeries}
              onCrosshairMove={handleCrosshair}
              chartApiRef={chartApiRef}
              mainSeriesRef={mainSeriesRef}
              onSeriesReady={handleSeriesReady}
            />
            <ChartOverlays
              chart={chartApi}
              mainSeries={mainSeries}
              signals={structureSignals}
              visibility={structureVisibility}
              visible={structureVisible}
            />
            <DrawingOverlays
              chart={chartApi}
              mainSeries={mainSeries}
              drawings={drawings.filter((d) => d.symbol === symbol && d.interval === interval)}
            />
            {mtfRows.length > 0 && <MtfDashboard rows={mtfRows} />}
            {showStructure && <StructurePanel onClose={() => setShowStructure(false)} />}
          </div>
        </div>
        <ChartRightPanel crosshairData={crosshair} symbol={symbol} structureSignals={structureSignals} indicatorLabels={indicatorLabels} />
      </div>
      {showAlerts && (
        <AlertRuleBuilder
          onClose={() => { setShowAlerts(false); setPrefillPrice(null); }}
          prefill={prefillPrice != null ? { price: prefillPrice } : null}
        />
      )}
      {clickPopover && clickPopover.kind === 'alert' && (
        <ChartClickPopover
          kind="alert"
          price={clickPopover.price}
          qty={1}
          onCancel={() => setClickPopover(null)}
          onConfirm={() => { setPrefillPrice(clickPopover.price); setShowAlerts(true); setClickPopover(null); }}
        />
      )}
      {clickPopover && clickPopover.kind === 'buy' && (
        <ChartClickPopover
          kind="buy"
          price={clickPopover.price}
          qty={buyQty}
          onQty={setBuyQty}
          onCancel={() => setClickPopover(null)}
          onConfirm={() => {
            const price = clickPopover.price;
            const qty = buyQty;
            // This toast is the FAST path — it only renders if the user is still
            // on a page mounting ChartWorkspace (this toast lives in AlertToast,
            // mounted here) when the POST resolves. If they navigate away first,
            // the toast never shows, but nothing is lost, for either outcome —
            // just via two DIFFERENT backstops:
            //  - rejected: addPosition already set portfolioStore's lastSyncError
            //    synchronously, which the Portfolio page's banner renders
            //    independently of navigation (Step 7's handleSubmit relies on
            //    that same synchronous-on-resolution guarantee from its own
            //    addPosition() call, not on reading lastSyncError itself).
            //  - pending:  the row stays 'pending' in local state and is
            //    auto-retried by syncFromBackend's poll (~30s) — it either lands
            //    silently (promoted to synced) or, if THAT retry is also
            //    rejected, surfaces via lastSyncError at that point instead.
            // (StockPositionCard and StockSendDialog now handle res.status ===
            // 'pending' too — StockPositionCard shows a "Queued — will sync" state,
            // StockSendDialog keeps the dialog open with a per-row queued note.)
            // Chart-click buy popover has no direction context to draw from — it's a
            // manual point-and-click entry, always long (there is no "sell"/"short"
            // popover kind; see ChartClickPopover's `kind: 'alert' | 'buy'` above).
            void usePortfolioStore.getState().addPosition(buildPaperStockPosition(symbol, price, qty, 'Bullish')).then((res) => {
              if (res.status === 'rejected') {
                useChartAlertStore.getState().pushToast({
                  id: `add-position-rejected-${rid()}`,
                  message: `${symbol} was not saved: ${res.detail ?? 'rejected by the backend'}`,
                  timestamp: Date.now(),
                });
              } else if (res.status === 'pending') {
                useChartAlertStore.getState().pushToast({
                  id: `add-position-pending-${rid()}`,
                  message: `${symbol} queued — backend unreachable, will sync automatically.`,
                  timestamp: Date.now(),
                });
              }
            });
            setClickPopover(null);
          }}
        />
      )}
      {textDraft && (
        <TextInputPopover
          initial={textDraft.editId ? drawings.find(d => d.id === textDraft.editId)?.text : undefined}
          onSave={(text) => {
            if (textDraft.editId) {
              updateDrawing(textDraft.editId, { text });
            } else {
              addDrawing({ id: rid(), symbol, interval, kind: 'text', points: [{ time: textDraft.time, price: textDraft.price }], color: drawingColorRef.current, width: 1, text, createdAt: new Date().toISOString() });
            }
            setTextDraft(null);
          }}
          onCancel={() => setTextDraft(null)}
        />
      )}
      <AlertToast />
    </div>
  );
}
