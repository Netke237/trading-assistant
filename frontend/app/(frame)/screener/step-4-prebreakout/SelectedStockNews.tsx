'use client';
import {useEffect, useState} from 'react';
import {api} from '@/lib/api';
import type {NewsItem} from '@/types/domain';
import {Text} from '@/components/primitives';
import styles from './page.module.css';

type NewsState = {symbol: string; status: 'ready'; items: NewsItem[]} | {symbol: string; status: 'error'};

/** Only an absolute http(s) link with a host is ever rendered as an anchor; anything else is unavailable. */
export function safeArticleUrl(url: unknown): string | null {
 if (typeof url !== 'string') return null;
 const candidate = url.trim();
 if (!candidate || /[\s\u0000-\u001f\u007f]/.test(candidate)) return null;
 try {
  const parsed = new URL(candidate);
  return (parsed.protocol === 'http:' || parsed.protocol === 'https:') && parsed.hostname ? parsed.href : null;
 } catch {
  return null;
 }
}

/** Provider timestamp shown in UTC; blank or unparseable stays unavailable rather than invented. */
export function newsDate(timestamp: string | null | undefined): string | null {
 if (typeof timestamp !== 'string' || !timestamp.trim()) return null;
 const ms = Date.parse(timestamp);
 if (!Number.isFinite(ms)) return null;
 return `${new Date(ms).toISOString().slice(0, 16).replace('T', ' ')} UTC`;
}

/** Selected-symbol headlines (api.getNews for that one symbol). The reply is owned by the
 * symbol it was requested for, so a late reply for a previous selection is never shown.
 * Loading/error/empty are local to this section and never touch the table, chart or context. */
export function SelectedStockNews({symbol}: {symbol: string | null}) {
 const [state, setState] = useState<NewsState | null>(null);
 useEffect(() => {
  setState(null);
  if (!symbol) return;
  let active = true;
  void Promise.resolve().then(() => api.getNews([symbol])).then(items => {
   if (active) setState({symbol, status: 'ready', items: Array.isArray(items) ? items : []});
  }).catch(() => {
   if (active) setState({symbol, status: 'error'});
  });
  return () => {active = false;};
 }, [symbol]);
 const current = symbol && state?.symbol === symbol ? state : null;
 return <section role="region" aria-label="Selected stock news" className={styles.contextSection}>
  <div className={styles.newsHeader}>
   <Text size={14} weight={500}>{symbol ?? 'Selected stock'} · Stock &amp; industry news</Text>
   <Text size={11} tone="dim">Headlines · publisher · date · original link</Text>
  </div>
  <Text size={11} tone="secondary">Selected-symbol headlines from the app&apos;s news feed{symbol ? ` · requested symbol ${symbol}` : ''}. Headlines are listed as supplied; no summaries or trading advice.</Text>
  {!symbol ? <Text size={12} tone="dim">Select a candidate to load its headlines.</Text>
   : !current ? <Text size={12} tone="dim">Loading headlines for {symbol}…</Text>
   : current.status === 'error' ? <Text size={12} tone="dim">Headlines unavailable for {symbol} — news request failed.</Text>
   : current.items.length === 0 ? <Text size={12} tone="dim">No headlines returned for {symbol}.</Text>
   : <ul className={styles.newsList}>{current.items.map((item, i) => {
    const href = safeArticleUrl(item.url);
    const date = newsDate(item.timestamp);
    const publisher = typeof item.source === 'string' && item.source.trim() ? item.source.trim() : null;
    const tagged = typeof item.symbol === 'string' && item.symbol.trim() ? item.symbol.trim() : null;
    return <li key={`${item.id}-${i}`} className={styles.newsItem}>
     <Text size={13}>{item.headline}</Text>
     <Text size={11} tone="secondary">
      {publisher ?? 'Publisher unavailable'} · {date ? <time dateTime={item.timestamp}>{date}</time> : 'Date unavailable'} · {tagged ? `Tagged ${tagged}` : 'Tagged symbol unavailable'}{tagged !== symbol ? ` · returned for requested ${symbol}` : ''}
     </Text>
     {href ? <a className={styles.newsLink} href={href} target="_blank" rel="noopener noreferrer">Original article ↗</a>
      : <Text size={11} tone="dim">Original link unavailable</Text>}
    </li>;
   })}</ul>}
  <Text size={11} tone="dim">Industry news unavailable — no supported industry mapping or industry news feed exists in the app.</Text>
 </section>;
}
