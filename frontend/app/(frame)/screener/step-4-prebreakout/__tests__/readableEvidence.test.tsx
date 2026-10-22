import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { SelectedRowEvidence } from '../PreBreakoutRowDetails';
import { RawEvidence } from '../RawEvidence';

const cases = [
  { mode: 'prebreakout' as const, row: { symbol:'PRE',direction:'Bearish',confidence:0,metrics:{atr_ratio:0},confidence_breakdown:{fib_used:false,weights:{atr:0.3},components:{atr:{score:0,weight:0.3,contribution:0}},unrounded:0.123456,confidence:0},fib_swing:{low:0,high:120} } },
  { mode: 'fib' as const, row: { symbol:'FIB',direction:'Bearish',confidence:0,fib_level_hit:'61.8%',fib_dist_pct:0,at_level:false,fib_swing:{low:0,high:120} } },
  { mode: 'pullback' as const, row: { symbol:'PULL',direction:'Bearish',stock_score:0,stock_status:'CAUTION',confidence:null,strategy:{entry_price:46.17,stop_price:48,target_price:42},gate_flags:[{gate:'confidence',status:'CAUTION',detail:'Confidence unavailable'}],custom_evidence:{observed:0,available:false,missing:null} } },
];

test.each(cases)('$mode normal evidence disclosures render fields instead of JSON while preserving the exact raw record', ({mode,row}) => {
  const {container}=render(<SelectedRowEvidence row={row as never} mode={mode} />);
  for (const details of container.querySelectorAll('details')) {
    const summary=details.querySelector('summary')!;
    if (!summary.textContent!.startsWith('Raw data:') && !details.open) fireEvent.click(summary);
  }
  expect(screen.getByText('Complete returned evidence')).toBeVisible();
  for (const dd of container.querySelectorAll('dd')) {
    expect(dd.textContent).not.toMatch(/^\s*\{/);
    expect(dd.textContent).not.toContain('[object Object]');
  }
  const raw=screen.getByText('Raw data: complete returned evidence').closest('details')!;
  expect(raw.open).toBe(false);
  expect(raw.querySelector('pre')).not.toBeVisible();
  fireEvent.click(screen.getByText('Raw data: complete returned evidence'));
  expect(raw.querySelector('pre')).toBeVisible();
  expect(JSON.parse(raw.querySelector('pre')!.textContent!)).toEqual(row);
});

test('readable nested fields keep zero, false, null and array entries distinct', () => {
  render(<SelectedRowEvidence mode="pullback" row={{symbol:'VALUES',direction:'Bullish',confidence:null,custom_evidence:{observed:0,available:false,missing:null,entries:[0,false,null]}} as never} />);
  const custom=screen.getByText('custom evidence').nextElementSibling!;
  expect(custom).toHaveTextContent('observed0');
  expect(custom).toHaveTextContent('availablefalse');
  expect(custom).toHaveTextContent('missingUnavailable (null)');
  expect(custom).toHaveTextContent('Item 10');
  expect(custom).toHaveTextContent('Item 2false');
  expect(custom).toHaveTextContent('Item 3Unavailable (null)');
});

test('legacy missing evidence stays unavailable and empty arrays stay empty', () => {
  render(<SelectedRowEvidence mode="prebreakout" row={{symbol:'OLD',direction:'Bullish',confidence:0,metrics:{},extra:[]} as never} />);
  fireEvent.click(screen.getByText('OLD · Setup evidence'));
  expect(screen.getByText('Confidence breakdown unavailable — this result contains no returned evidence.')).toBeVisible();
  expect(screen.getByText('0 items')).toBeVisible();
});

test('a replacement result for the same symbol closes its raw disclosure', () => {
  const row=cases[0].row;
  const view=render(<SelectedRowEvidence row={row as never} mode="prebreakout" />);
  fireEvent.click(screen.getByText('PRE · Setup evidence'));
  fireEvent.click(screen.getByText('Raw data: complete returned evidence'));
  expect(screen.getByText('Raw data: complete returned evidence').closest('details')!.open).toBe(true);
  const next={...row,confidence:81};
  view.rerender(<SelectedRowEvidence row={next as never} mode="prebreakout" />);
  const raw=screen.getByText('Raw data: complete returned evidence').closest('details')!;
  expect(raw.open).toBe(false);
  expect(JSON.parse(raw.querySelector('pre')!.textContent!)).toEqual(next);
});

test('supplementary raw evidence remains opt-in when its source changes', () => {
  const view=render(<RawEvidence label="supplementary context" value={{symbol:'A',score:0}} />);
  fireEvent.click(screen.getByText('Raw data: supplementary context'));
  expect(screen.getByText('Raw data: supplementary context').closest('details')!.open).toBe(true);
  view.rerender(<RawEvidence label="supplementary context" value={{symbol:'B',score:80}} />);
  const raw=screen.getByText('Raw data: supplementary context').closest('details')!;
  expect(raw.open).toBe(false);
  expect(JSON.parse(raw.querySelector('pre')!.textContent!)).toEqual({symbol:'B',score:80});
});
