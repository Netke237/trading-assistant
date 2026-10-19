import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { LegacyReport } from '../LegacyReport';

test('opening legacy summaries shows saved metadata and candidates while raw JSON stays hidden', () => {
  const entry = {
    run_id: 'legacy:current', status: 'complete', category: 'legacy/unclassified',
    started_at: '2026-07-13T15:03:20Z', ended_at: '2026-10-15T16:21:59Z',
    inputs: { direction: 'Bearish', horizon: 'Swing', category: 'stocks' },
    result: { candidates: [
      { symbol: 'MKC', direction: 'Bearish', stockScore: 62, stockConfidence: 'CAUTION' },
      { symbol: 'ZERO', direction: 'Bearish', stock_score: 0, confidence: 0 },
    ] },
  };
  render(<LegacyReport entry={entry} />);
  const summary = screen.getByText('legacy:current · complete');
  expect(summary.closest('details')!.open).toBe(false);
  fireEvent.click(summary);
  expect(screen.getByText(entry.started_at)).toBeVisible();
  expect(screen.getByText(entry.ended_at)).toBeVisible();
  expect(screen.getByText('Candidate records').nextElementSibling).toHaveTextContent('2');
  const table = screen.getByRole('table', { name: 'Saved candidate records' });
  expect(within(table).getByRole('rowheader', { name: 'MKC' })).toBeVisible();
  expect(within(table).getByRole('rowheader', { name: 'ZERO' })).toBeVisible();
  expect(within(table).queryByRole('columnheader', { name: /score|confidence|status/i })).not.toBeInTheDocument();
  expect(document.querySelectorAll('pre')).toHaveLength(3);
  for (const pre of document.querySelectorAll('pre')) expect(pre).not.toBeVisible();
  fireEvent.click(screen.getByText('Raw data'));
  const raw = screen.getByText('Raw data').closest('details')!.querySelector('pre')!;
  expect(raw).toBeVisible();
  expect(JSON.parse(raw.textContent!)).toEqual(entry);
});

test.each([null, [], { candidates: null }, { candidates: [null, { symbol: 'PARTIAL' }] }])('unsupported legacy result %j stays unavailable rather than showing zero candidates', result => {
  const entry = { run_id: 'legacy:unknown', status: 'complete', inputs: null, result };
  render(<LegacyReport entry={entry} />);
  fireEvent.click(screen.getByText('legacy:unknown · complete'));
  expect(screen.getByText('Candidate records').nextElementSibling).toHaveTextContent('Unavailable');
  expect(screen.getByText('Candidate records unavailable in this legacy format.')).toBeVisible();
  expect(screen.queryByRole('table')).not.toBeInTheDocument();
  expect(JSON.parse(screen.getByText('Raw data').closest('details')!.querySelector('pre')!.textContent!)).toEqual(entry);
});

test('empty recorded candidates are distinct from unavailable data and explicit unavailable input markers are honored', () => {
  render(<LegacyReport entry={{
    run_id: 'legacy:empty', status: 'complete',
    inputs: { direction: 'Bearish', direction_unavailable: true, horizon: '', horizon_unavailable: true },
    result: { candidates: [] },
  }} />);
  fireEvent.click(screen.getByText('legacy:empty · complete'));
  expect(screen.getByText('Candidate records').nextElementSibling).toHaveTextContent('0');
  expect(screen.getByText('Recorded direction').nextElementSibling).toHaveTextContent('Unavailable');
  expect(screen.getByText('Recorded horizon').nextElementSibling).toHaveTextContent('Unavailable');
  expect(screen.getByText('No candidate records saved.')).toBeVisible();
});
test.each([{candidates:[]}, {candidates:[{symbol:'READABLE'}]}])('omitted legacy candidate elements make the total unavailable while retaining readable rows: %j', ({candidates}) => {
  // get_legacy records this path when project omits an unsupported candidate.
  const entry = {
    run_id:'legacy:omitted',status:'complete',result:{candidates},
    unavailable_fields:['result'],unavailable_field_paths:{result:['result.candidates[0]']},
  };
  render(<LegacyReport entry={entry} />);
  fireEvent.click(screen.getByText('legacy:omitted · complete'));
  expect(screen.getByText('Candidate records').nextElementSibling).toHaveTextContent('Unavailable');
  expect(screen.getByText('Candidate records are incomplete; some legacy records are unavailable.')).toBeVisible();
  expect(screen.queryByText('No candidate records saved.')).not.toBeInTheDocument();
  if (candidates.length) expect(screen.getByRole('rowheader',{name:'READABLE'})).toBeVisible();
  expect(JSON.parse(screen.getByText('Raw data').closest('details')!.querySelector('pre')!.textContent!)).toEqual(entry);
});
test('omitted nested fields do not remove known candidate records', () => {
  render(<LegacyReport entry={{run_id:'legacy:fields',status:'complete',result:{candidates:[{symbol:'KNOWN'}]},unavailable_fields:['result'],unavailable_field_paths:{result:['result.candidates[0].company']}}} />);
  fireEvent.click(screen.getByText('legacy:fields · complete'));
  expect(screen.getByText('Candidate records').nextElementSibling).toHaveTextContent('1');
  expect(screen.getByRole('rowheader',{name:'KNOWN'})).toBeVisible();
});
