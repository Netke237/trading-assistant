'use client';
import { useEffect, useRef, useState, useCallback, useMemo } from 'react';
import { useSearchParams } from 'next/navigation';
import { useChartStore, type IndicatorConfig, type Interval } from '@/lib/chartStore';
import { ChartWSClient, type WSMessage } from '@/lib/chartWS';
import { calcEMA, calcSMA, calcRSI, calcMACD, calcBB, calcATR, calcVWAP, type Candle } from '@/lib/indicators';
import { useStructureStore } from '@/lib/structureStore';
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

function buildMainSeries(candles: Candle[], indicators: IndicatorConfig[]): SeriesConfig[] {
  const series: SeriesConfig[] = [
    { id: 'candles', type: 'Candlestick', data: candles },
  ];
  for (const ind of indicators) {
    if (ind.pane !== 'main') continue;
    if (ind.type === 'EMA')  series.push({ id: ind.id, type: 'Line', data: calcEMA(candles, ind.params.period ?? 20), color: ind.color });
    if (ind.type === 'SMA')  series.push({ id: ind.id, type: 'Line', data: calcSMA(candles, ind.params.period ?? 20), color: ind.color });
    if (ind.type === 'VWAP') series.push({ id: ind.id, type: 'Line', data: calcVWAP(candles), color: ind.color });
    if (ind.type === 'BB') {
      const bb = calcBB(candles, ind.params.period ?? 20, ind.params.stdDev ?? 2);
      series.push({ id: `${ind.id}-upper`, type: 'Line', data: bb.upper, color: ind.color });
      series.push({ id: `${ind.id}-mid`,   type: 'Line', data: bb.middle, color: ind.color });
      series.push({ id: `${ind.id}-lower`, type: 'Line', data: bb.lower, color: ind.color });
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

// ── Component ─────────────────────────────────────────────────────────────────

export default function ChartWorkspace() {
  const params = useSearchParams();
  const { symbol, interval, activeIndicators, setSymbol, setInterval } = useChartStore();
  const [candles, setCandles] = useState<Candle[]>([]);
  const [drawingTool, setDrawingTool] = useState<DrawingTool>('cursor');
  const [showIndicators, setShowIndicators] = useState(false);
  const [showStructure, setShowStructure] = useState(false);
  const [crosshair, setCrosshair] = useState<DataValues>({ time: null, indicators: {} });
  const wsRef = useRef<ChartWSClient | null>(null);
  const chartApiRef = useRef<IChartApi | null>(null);
  const mainSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);

  const structureVisible = useStructureStore((s) => s.structureVisible);
  const structureVisibility = useStructureStore((s) => s.visibility);
  const structureSignals = useStructureStore((s) => s.signals[`${symbol}:${interval}`] ?? []);

  // Deep-link: read ?symbol= and ?interval= query params once on mount
  useEffect(() => {
    const sym = params?.get('symbol');
    const iv  = params?.get('interval');
    if (sym) setSymbol(sym.toUpperCase());
    if (iv)  setInterval(iv as Interval);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // intentionally run only once on mount

  // Connect/reconnect WebSocket when symbol or interval changes
  useEffect(() => {
    wsRef.current?.destroy();

    // Map store interval labels to backend interval strings
    const backendInterval =
      interval === '1D' ? 'daily' :
      interval === '1W' ? 'weekly' :
      interval;

    const client = new ChartWSClient(symbol, backendInterval);
    const unsubscribe = client.onMessage((msg: WSMessage) => {
      if (msg.type === 'history') {
        setCandles(msg.candles);
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
    });
    client.connect();
    wsRef.current = client;

    return () => {
      unsubscribe();
      client.destroy();
    };
  }, [symbol, interval]);

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

  const mainSeries = useMemo(() => buildMainSeries(candles, activeIndicators), [candles, activeIndicators]);
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
      />
      {showIndicators && <IndicatorPanel onClose={() => setShowIndicators(false)} />}
      {showStructure && <StructurePanel onClose={() => setShowStructure(false)} />}
      <div className={styles.body}>
        <DrawingToolbar active={drawingTool} onChange={setDrawingTool} />
        <div className={styles.charts}>
          <div style={{ position: 'relative' }}>
            <ChartPane
              series={mainSeries}
              height={320}
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
          </div>
          {subPanes.map(({ id, series }) => (
            <ChartPane key={id} series={series} height={100} />
          ))}
        </div>
        <ChartRightPanel crosshairData={crosshair} />
      </div>
    </div>
  );
}
