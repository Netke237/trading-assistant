import { test, expect } from '@playwright/test';
import { setupApiMocks } from '../fixtures/api-mocks';
import type { BacktestArtifact } from '@/types/backtest';

function buildMockArtifact(symbol: string, strategy: string, artifactId: string): BacktestArtifact {
  const baseTime = 1704067200; // 2024-01-01T00:00:00Z
  const candles = Array.from({ length: 120 }, (_, i) => ({
    time: baseTime + i * 86400,
    open: 100 + i * 0.1,
    high: 102 + i * 0.1,
    low: 99 + i * 0.1,
    close: 101 + i * 0.1,
    volume: 1000000,
  }));

  const equity = Array.from({ length: 120 }, (_, i) => ({
    time: baseTime + i * 86400,
    equity: 100000 + i * 100,
    strategy_index: 100 + i * 0.1,
    benchmark_index: 100 + i * 0.05,
  }));

  return {
    schema_version: 1,
    artifact_id: artifactId,
    provenance: 'original',
    identity: {
      scan_id: 'scan-setup-001',
      report_run_id: null,
      symbol,
      strategy,
      direction: 'Bullish',
      horizon: 'Swing',
      interval: '1d',
      bars_basis_version: 'test-basis',
      input_hash: 'a'.repeat(64),
      engine_contract_version: 'backtesting-0.6.6-v2',
    },
    created_at: baseTime,
    expires_at: baseTime + 30 * 86400,
    currency: null,
    detail: {
      summary: {
        strategy,
        direction: 'Bullish',
        n_trades: 1,
        win_rate: 1.0,
        total_return_pct: 12.0,
        max_drawdown_pct: 2.5,
        expectancy: 120.0,
        sharpe: 1.8,
        confidence: 80,
        passes_gate: true,
        summary_text: '1 trades — Win 100% — Return 12.0%',
        n_time_exits: 0,
      },
      status: 'success',
      reason: null,
      input_candles: candles,
      candles,
      equity,
      trades: [
        {
          id: 'trade-001',
          direction: 'Bullish',
          entry_time: baseTime + 50 * 86400,
          exit_time: baseTime + 65 * 86400,
          entry_price: 105.0,
          exit_price: 118.0,
          size: 100,
          net_return_pct: 12.0,
          commission: 0.002,
          exit_reason: 'target' as any,
        },
      ],
      open_positions: [],
      initial_equity: 100000,
      configuration: {
        initial_cash: 100000,
        commission: 0.002,
        commission_basis: 'fraction',
        order_size: 1.0,
        sizing: 'whole',
        margin: 1.0,
        spread: 0.0,
        exclusive_orders: true,
        trade_on_close: false,
        finalize_trades: false,
        hold_max_days: 15,
        entry_start: null,
        entry_end: null,
      },
      effective_params: {
        require_trend: false,
      },
      engine_contract_version: 'backtesting-0.6.6-v2',
      time_basis: 'UTC epoch seconds',
    },
  };
}

test.describe('SETUP-BACKTEST-CHART (#391): Pre-Breakout & Fib Pullback candidate chart curves', () => {
  test('direct chart URL renders historical candles and equity comparison for prebreakout candidate', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 1000 });
    await setupApiMocks(page);

    const artifact = buildMockArtifact('PRESYM', 'breakout_setup', 'c8b41724-4f45-4bb6-a973-123456789abc');

    await page.route('**/api/backtest-artifacts/c8b41724-4f45-4bb6-a973-123456789abc**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(artifact),
      });
    });

    await page.goto('/chart?symbol=PRESYM&source=prebreakout&backtest_artifact_status=available&backtest_artifact_id=c8b41724-4f45-4bb6-a973-123456789abc');

    // Historical candles pane and equity comparison pane must be visible
    await expect(page.getByLabel('Historical candles', { exact: true })).toBeVisible();
    await expect(page.getByLabel('Indexed equity comparison', { exact: true })).toBeVisible();

    // Inspect trade button should be available
    const inspectBtn = page.getByRole('button', { name: 'Inspect trade trade-001', exact: true });
    await expect(inspectBtn).toBeVisible();
    await inspectBtn.click();

    const tradeInspector = page.getByLabel('Trade inspector', { exact: true });
    await expect(tradeInspector).toBeVisible();
    await expect(tradeInspector).toContainText('105');
    await expect(tradeInspector).toContainText('118');
  });

  test('direct chart URL renders historical candles and equity comparison for fib candidate', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 1000 });
    await setupApiMocks(page);

    const artifact = buildMockArtifact('FIBSYM', 'fibonacci_pullback', 'd9c52835-5f56-4cc7-ba84-234567890def');

    await page.route('**/api/backtest-artifacts/d9c52835-5f56-4cc7-ba84-234567890def**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(artifact),
      });
    });

    await page.goto('/chart?symbol=FIBSYM&source=fib&backtest_artifact_status=available&backtest_artifact_id=d9c52835-5f56-4cc7-ba84-234567890def');

    await expect(page.getByLabel('Historical candles', { exact: true })).toBeVisible();
    await expect(page.getByLabel('Indexed equity comparison', { exact: true })).toBeVisible();
  });

  test('unavailable reason renders in plain explanatory words', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 1000 });
    await setupApiMocks(page);

    await page.goto('/chart?symbol=TEST&source=prebreakout&backtest_artifact_status=insufficient_history');

    const statusRole = page.getByRole('status');
    await expect(statusRole).toBeVisible();
    await expect(statusRole).toContainText('Original backtest unavailable: insufficient_history (not enough price bars to run the backtest)');
  });
});
