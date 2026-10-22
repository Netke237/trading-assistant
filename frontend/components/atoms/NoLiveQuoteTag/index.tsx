import { Text } from '@/components/primitives';
import { quoteWarning } from '@/lib/quoteWarning';
export function NoLiveQuoteTag({ noLiveQuote, quoteState }: { noLiveQuote?: boolean; quoteState?: string | null }) {
  return noLiveQuote ? <span title={quoteWarning({ quoteLive: false, quoteState }) ?? undefined}><Text size={10} tone="caution">no live quote</Text></span> : null;
}

