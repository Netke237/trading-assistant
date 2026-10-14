import { create } from 'zustand';
import type { OptionsPipeline, RejectedEntry } from './scanStore';
import type { StockPipeline } from '@/types/stockDomain';
export type ScanReportCategory = 'options' | 'stocks' | 'prebreakout' | 'pullback' | 'fib';
// Setup-scan terminal outcomes (diagnostics.terminal_outcomes, version 1), recorded by
// backend scan_report_lifecycle.Collector.terminal_snapshot for prebreakout / fib /
// pullback runs only. Older runs and other categories omit it entirely.
export type TerminalOutcomeKind = 'accepted' | 'excluded' | 'no_data' | 'error' | 'no_setup' | 'filtered';
export type TerminalOutcomeValue = number | string | boolean;
export interface TerminalOutcomeRecord {
    symbol: string;
    terminal: TerminalOutcomeKind;
    code: string;
    observations?: Record<string, TerminalOutcomeValue>;
    thresholds?: Record<string, TerminalOutcomeValue>;
}
export interface TerminalOutcomes {
    version: number;
    resolution_available: boolean;
    complete: boolean;
    input_symbols: string[];
    evaluated_symbols: string[];
    outcomes: TerminalOutcomeRecord[];
    counts: {
        accepted: number;
        excluded: number;
        no_data: number;
        error_count: number;
        no_setup: number;
        filtered: number;
        input: number | null;
        evaluated: number | null;
    };
    unknown_symbols: string[];
    diagnostic_unavailable?: boolean;
}
export interface ScanReport {
    category: ScanReportCategory;
    run_id: string;
    generation: number;
    trigger: string;
    started_at: string;
    ended_at: string | null;
    status: string;
    persistence: string;
    dispatch_inputs?: Record<string, unknown>;
    inputs: Record<string, unknown> | null;
    diagnostics_available: boolean;
    diagnostics: {
        pipeline?: OptionsPipeline | StockPipeline;
        rejected?: RejectedEntry[];
        accepted_symbols?: string[];
        terminal_outcomes?: TerminalOutcomes;
        [key: string]: unknown;
    } | null;
    result: Record<string, unknown> | null;
}
export interface LatestScanReport {
    category: ScanReportCategory;
    latest_attempt: ScanReport | null;
    previous_report: ScanReport | null;
}
export interface ScanReportMetadata {
    run_id: string;
    generation: number;
    persistence: string;
    accepted_symbols?: string[];
    pipeline_counts?: Record<string, number>;
    failed?: boolean;
}
// Ephemeral table linkage only. Durable reports always come from the system API.
export const useScanReportUpdates = create<{
    revision: number;
    current: Partial<Record<ScanReportCategory, ScanReportMetadata>>;
    record: (category: ScanReportCategory, value: ScanReportMetadata) => void;
}>((set) => ({
    revision: 0, current: {}, record: (category, value) => set(s => !s.current[category] || value.generation >= s.current[category]!.generation ? { revision: s.revision + 1, current: { ...s.current, [category]: value } } : s),
}));
