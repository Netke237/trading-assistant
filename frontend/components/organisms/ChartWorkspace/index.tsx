'use client';
import { useEffect, useRef, useState, useCallback, useMemo } from 'react';
import { useSearchParams } from 'next/navigation';
import { useChartStore, type IndicatorConfig, type Interval, type ChartType } from '@/lib/chartStore';
import { ChartWSClient, type WSMessage, type ConnectionState } from '@/lib/chartWS';
import { calcEMA, calcSMA, calcRSI, calcMACD, calcBB, calcATR, calcVWAP, type Candle, type Point } from '@/lib/indicators';
import { useStructureStore } from '@/lib/structureStore';
import type { StructureSignal } from '@/types/structure';
import { useChartAlertStore } from '@/lib/chartAlertStore';
import { evaluateRules } from '@/lib/chartAlertEngine';
import AlertRuleBuilder from '@/components/organisms/AlertRuleBuilder';
import AlertToast from '@/components/organisms/AlertToast';
import type { SeriesConfig } from '@/components/organisms/ChartPane';
import ChartPane from '@/components/organisms/ChartPane';
import ChartTopBar from '@/components/organisms/ChartTopBar';
import DrawingToolbar, { type DrawingTool } from '@/components/organisms/DrawingToolbar';
import IndicatorPanel from '@/components/organisms/IndicatorPanel';
import StructurePanel from '@/components/organisms/StructurePanel';
import { ChartOverlays } from '@/components/organisms/ChartOverlays';
import ChartRightPanel, { type DataValues } from '@/components/organisms/ChartRightPanel';
import type { IChartApi, ISeriesApi } from 'lightweight-charts';
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
  }
  return series;
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

export default function ChartWorkspace() {
  const params = useSearchParams();
  const { symbol, interval, chartType, activeIndicators, setSymbol, setInterval } = useChartStore();
  const [candles, setCandles] = useState<Candle[]>([]);
  const [drawingTool, setDrawingTool] = useState<DrawingTool>('cursor');
  const [showIndicators, setShowIndicators] = useState(false);
  const [showStructure, setShowStructure] = useState(false);
  const [showAlerts, setShowAlerts] = useState(false);
  const [crosshair, setCrosshair] = useState<DataValues>({ time: null, indicators: {} });
  const [connState, setConnState] = useState<ConnectionState>('connecting');
  const [wsError, setWsError] = useState<string | null>(null);
  const wsRef = useRef<ChartWSClient | null>(null);
  const chartApiRef = useRef<IChartApi | null>(null);
  const mainSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);

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

  // Sync alert rules from backend on mount
  useEffect(() => {
    useChartAlertStore.getState().syncRules();
  }, []);

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
        useChartAlertStore.getState().addHistory(msg.entry);
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
        const triggered = evaluateRules(
          alertRules,
          closedCandle,
          candles,
          indicatorPoints,
          structureSignals,
          new Date(),
          symbol,
          interval,
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

  const mainSeries = useMemo(
    () => buildMainSeries(candles, activeIndicators, chartType, interval),
    [candles, activeIndicators, chartType, interval],
  );
  const subPanes = useMemo(
    () => activeIndicators
      .filter(i => i.pane === 'sub')
      .map(ind => ({ id: ind.id, series: buildSubSeries(candles, ind) })),
    [candles, activeIndicators],
  );

  return (
    <div className={styles.workspace}>
      <ChartTopBar
        onToggleIndicators={() => setShowIndicators(v => !v)}
        onToggleStructure={() => setShowStructure(v => !v)}
        onToggleAlerts={() => setShowAlerts(v => !v)}
        connState={connState}
        wsError={wsError}
      />
      {showIndicators && <IndicatorPanel onClose={() => setShowIndicators(false)} />}
      <div className={styles.body}>
        <DrawingToolbar active={drawingTool} onChange={setDrawingTool} />
        <div className={styles.charts}>
          <div className={styles.mainPane}>
            <ChartPane
              series={mainSeries}
              onCrosshairMove={handleCrosshair}
              chartApiRef={chartApiRef}
              mainSeriesRef={mainSeriesRef}
            />
            <ChartOverlays
              chart={chartApiRef.current}
              mainSeries={mainSeriesRef.current}
              signals={structureSignals}
              visibility={structureVisibility}
              visible={structureVisible}
            />
            {showStructure && <StructurePanel onClose={() => setShowStructure(false)} />}
          </div>
          {subPanes.map(({ id, series }) => (
            <ChartPane key={id} series={series} height={100} />
          ))}
        </div>
        <ChartRightPanel crosshairData={crosshair} symbol={symbol} structureSignals={structureSignals} />
      </div>
      {showAlerts && <AlertRuleBuilder onClose={() => setShowAlerts(false)} />}
      <AlertToast />
    </div>
  );
}
