import { create } from 'zustand';
import type { OptionsPipeline, RejectedEntry } from './scanStore';
import type { StockPipeline } from '@/types/stockDomain';
export type ScanReportCategory = 'options' | 'stocks' | 'prebreakout' | 'pullback' | 'fib';
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
