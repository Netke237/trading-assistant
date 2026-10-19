'use client';
import React, { useEffect, useRef, useState } from 'react';
import { useCurrentScanReportInputs } from '@/lib/currentScanReportInputs';
import { api } from '@/lib/api';
import { useScanReportUpdates, type LatestScanReport, type ScanReportCategory } from '@/lib/scanReports';
import type { OptionsPipeline } from '@/lib/scanStore';
import type { StockPipeline } from '@/types/stockDomain';
import { PipelineInspector } from '@/components/organisms/PipelineInspector';
import { SavedScanResultsTable } from '@/components/molecules/SavedScanResultsTable';
import { TerminalOutcomes, TERMINAL_OUTCOME_CATEGORIES } from './TerminalOutcomes';
import { LegacyReport } from './LegacyReport';
import { UnsavedReport } from './UnsavedReport';
import { SavedExclusions } from './SavedExclusions';
import styles from './SavedScanReportInspector.module.css';
const categories: ScanReportCategory[] = ['options', 'stocks', 'prebreakout', 'pullback', 'fib'];
const labels: Record<ScanReportCategory, string> = { options: 'Options', stocks: 'Stocks', prebreakout: 'Pre-Breakout', pullback: 'Pullback', fib: 'Fib Pullback' };
interface Props {
    category: ScanReportCategory;
    currentInputs?: Record<string, unknown>;
    isOpen?: boolean;
    isDrawer?: boolean;
    onClose?: () => void;
    tableRunId?: string | null;
}
function json(value: unknown) { return JSON.stringify(value, null, 2); }
function canonical(value: unknown): string | undefined { return JSON.stringify(value, (_, v) => v && typeof v === 'object' && !Array.isArray(v) ? Object.fromEntries(Object.keys(v).filter(k => v[k] != null).sort().map(k => [k, v[k]])) : v ?? undefined); }
export function scanReportInputsDiffer(frozen: Record<string, unknown>, current: Record<string, unknown>): boolean {
    return Array.from(new Set([...Object.keys(frozen), ...Object.keys(current)])).filter(key => key !== 'category').some(key => canonical(frozen[key]) !== canonical(current[key]));
}
export function SavedScanReportInspector({ category, currentInputs, isOpen = true, isDrawer = false, onClose, tableRunId }: Props) {
    const liveInputs = useCurrentScanReportInputs(category);
    const comparedInputs = currentInputs ?? liveInputs;
    const [selected, setSelected] = useState<ScanReportCategory | 'legacy'>(category);
    const [data, setData] = useState<LatestScanReport | null>(null);
    const [legacy, setLegacy] = useState<Record<string, unknown>[] | null>(null);
    const [error, setError] = useState(false);
    const [previous, setPrevious] = useState(false);
    const [loading, setLoading] = useState(false);
    const [refresh, setRefresh] = useState(0);
    const drawerRef = useRef<HTMLElement>(null);
    const closeRef = useRef(onClose);
    closeRef.current = onClose;
    const generations = useRef<Partial<Record<ScanReportCategory, LatestScanReport>>>({});
    const revision = useScanReportUpdates(s => s.revision);
    const updates = useScanReportUpdates(s => s.current);
    useEffect(() => { setSelected(category); setPrevious(false); }, [category]);
    useEffect(() => {
        if (!isOpen)
            return;
        const controller = new AbortController();
        let active = true;
        setData(null);
        setLegacy(null);
        setError(false);
        setLoading(true);
        Promise.resolve().then<LatestScanReport | Record<string, unknown>[]>(() => selected === 'legacy' ? api.getLegacyScanReports(controller.signal) : api.getLatestScanReport(selected, controller.signal)).then(value => {
            if (!active)
                return;
            if (selected === 'legacy')
                setLegacy(value as Record<string, unknown>[]);
            else {
                const incoming = value as LatestScanReport;
                if (incoming.category !== selected)
                    return;
                const cached = generations.current[selected];
                const incomingGeneration = incoming.latest_attempt?.generation ?? -1;
                const cachedGeneration = cached?.latest_attempt?.generation ?? -1;
                const terminalAlreadyRead = incomingGeneration === cachedGeneration && cached?.latest_attempt?.status !== 'running' && incoming.latest_attempt?.status === 'running';
                const accepted = incomingGeneration < cachedGeneration || terminalAlreadyRead ? cached! : incoming;
                generations.current[selected] = accepted;
                setData(accepted);
            }
        }).catch(() => { if (active)
            setError(true); }).finally(() => { if (active)
            setLoading(false); });
        return () => { active = false; controller.abort(); };
    }, [selected, isOpen, revision, refresh]);
    useEffect(() => {
        if (!isOpen || !isDrawer)
            return;
        const opener = document.activeElement as HTMLElement | null;
        drawerRef.current?.querySelector<HTMLButtonElement>('button')?.focus();
        const handler = (e: KeyboardEvent) => {
            if (e.key === 'Escape') {
                e.preventDefault();
                closeRef.current?.();
            }
            if (e.key !== 'Tab')
                return;
            const elements = Array.from(drawerRef.current?.querySelectorAll<HTMLElement>('button:not([disabled]),select,input,summary,a[href]') ?? []).filter(element => {
                for (let parent = element.parentElement; parent && parent !== drawerRef.current; parent = parent.parentElement) {
                    if (parent.hidden)
                        return false;
                    if (parent instanceof HTMLDetailsElement && !parent.open && !parent.querySelector('summary')?.contains(element))
                        return false;
                }
                return true;
            });
            if (!elements?.length)
                return;
            const first = elements[0], last = elements[elements.length - 1];
            if (e.shiftKey && document.activeElement === first) {
                e.preventDefault();
                last.focus();
            }
            else if (!e.shiftKey && document.activeElement === last) {
                e.preventDefault();
                first.focus();
            }
        };
        window.addEventListener('keydown', handler);
        return () => { window.removeEventListener('keydown', handler); opener?.focus?.(); };
    }, [isOpen, isDrawer]);
    useEffect(() => {
        if (!isOpen || data?.latest_attempt?.status !== 'running')
            return;
        const timer = setTimeout(() => setRefresh(v => v + 1), 3000);
        return () => clearTimeout(timer);
    }, [isOpen, data]);
    if (!isOpen)
        return null;
    const report = data?.category === selected ? (previous ? data.previous_report : data.latest_attempt) : null;
    const update = selected === 'legacy' ? undefined : updates[selected];
    const unsaved = update?.persistence === 'unavailable' && update.generation >= (data?.latest_attempt?.generation ?? -1);
    const frozen = report?.inputs?.request as Record<string, unknown> | undefined;
    const mismatch = selected === category && frozen && comparedInputs && scanReportInputsDiffer(frozen, comparedInputs);
    const diagnostics = report?.diagnostics;
    const pipeline = report?.diagnostics_available ? diagnostics?.pipeline : undefined;
    const result = report?.result;
    const exclusions = diagnostics?.excluded ?? report?.inputs?.excluded;
    const content = <section ref={drawerRef} className={isDrawer ? styles.drawer : styles.container} role={isDrawer ? 'dialog' : 'region'} aria-label="Saved scan report" aria-modal={isDrawer || undefined}>
  <div className={styles.actions}><h2>Saved scan report</h2>{onClose && <button type="button" onClick={onClose} aria-label="Close inspector">Close</button>}</div>
  <div className={styles.controls}><label>Report category <select aria-label="Report category" value={selected} onChange={e => { setSelected(e.target.value as typeof selected); setPrevious(false); }}>{categories.map(c => <option key={c} value={c}>{labels[c]}</option>)}<option value="legacy">Legacy / unclassified</option></select></label>
  <button type="button" onClick={() => setRefresh(v => v + 1)}>Refresh report</button></div>
  {loading && <p role="status">Loading saved report…</p>}
  {error && <p role="alert">Saved report storage unavailable.</p>}
  {selected === category && !comparedInputs && <p role="status">Current controls comparison unavailable; saved reports retain their frozen inputs.</p>}
  {unsaved && <UnsavedReport update={update} />}
  {data?.category === selected && data.previous_report && <div className={styles.actions}><button type="button" aria-pressed={!previous} onClick={() => setPrevious(false)}>Latest attempt</button><button type="button" aria-pressed={previous} onClick={() => setPrevious(true)}>Previous saved report</button></div>}
  {!loading && !error && selected !== 'legacy' && !report && <p>No saved report available.</p>}
  {report && <>
   {previous && <p>Previous saved evidence; latest attempt {data?.latest_attempt?.run_id} is {data?.latest_attempt?.status}.</p>}
   <h3>Run {report.run_id}</h3><p>{report.category} · {report.status} · {report.trigger} · generation {report.generation} · {report.persistence}</p>
   <p>Started {report.started_at} · Ended {report.ended_at ?? 'not ended'}</p>
   <p>Displayed table run: {selected === category ? (tableRunId ?? 'unavailable') : 'another category'}. Saved evidence has its own run identity.</p>
   {mismatch && <p role="status">Current controls differ from this saved run. Evidence uses the frozen inputs below.</p>}
   <details key={`${report.run_id}:inputs`}><summary>Raw frozen inputs and configuration</summary><pre>{json(report.inputs)}</pre><p>{report.inputs?.effective_configuration_complete === true ? 'Effective configuration recorded.' : 'Effective configuration incomplete; comparison of unavailable settings is unavailable. Recorded fields are in the snapshot.'}</p></details>
   {pipeline ? (report.category === 'options' ? <PipelineInspector key={report.run_id} isDrawer={false} pipeline={pipeline as OptionsPipeline} rejected={diagnostics?.rejected} survivors={diagnostics?.accepted_symbols} contractRules={result?.contract_rules as Record<string, number> | undefined} dteWindow={result?.dte_window as import('@/types/domain').DteWindow | undefined}/> : <PipelineInspector key={report.run_id} mode="stock" isDrawer={false} pipeline={pipeline as StockPipeline} rejected={diagnostics?.rejected} survivors={diagnostics?.accepted_symbols}/>) : <p>Diagnostics unavailable: stage counts and rejection reasons were not recorded for this run.</p>}
   {TERMINAL_OUTCOME_CATEGORIES.includes(report.category) && <TerminalOutcomes key={report.run_id} value={diagnostics?.terminal_outcomes} runId={report.run_id} tableRunId={tableRunId} sameCategory={selected === category}/>}
   {Array.isArray(result?.candidates) && <SavedScanResultsTable key={`${report.run_id}:results`} category={report.category} rows={result.candidates as Record<string, unknown>[]} />}
   {Array.isArray(exclusions) && <SavedExclusions key={`${report.run_id}:exclusions`} rows={exclusions} />}
   <details key={`${report.run_id}:raw`}><summary>Raw report data</summary><pre>{json({ diagnostics: report.diagnostics, result: report.result })}</pre></details>
  </>}
  {selected === 'legacy' && legacy && <><p>Legacy / unclassified evidence. Category, effective settings and diagnostics may be unavailable; no category has been inferred.</p>{TERMINAL_OUTCOME_CATEGORIES.includes(category) && <p>Terminal outcome diagnostics unavailable for legacy / unclassified runs.</p>}{legacy.length === 0 ? <p>No legacy evidence available.</p> : legacy.map((entry, i) => <LegacyReport key={`${String(entry.run_id)}:${i}`} entry={entry} />)}</>}
 </section>;
    return isDrawer ? <><div className={styles.backdrop} onClick={onClose} aria-hidden/>{content}</> : content;
}
