import React from 'react';
import { render, screen, fireEvent, within } from '@testing-library/react';
import { BacktestTradeTable, type TradeRowView } from '../index';

const rows: TradeRowView[] = [
 {id:'a', label:'Trade #a · Bearish', entry:'2023-11-14 22:13', exit:'2023-11-15 22:13', prices:'43.13 / 39.88', returnText:'+7.12%', returnTone:'pass', reason:'Unknown (not recorded by engine)'},
 {id:'b', label:'Trade #b · Bullish', entry:'2023-11-16 22:13', exit:'2023-11-17 22:13', prices:'40.00 / 39.00', returnText:'-2.50%', returnTone:'reject', reason:'Time exit (holding limit)'},
];

it('renders readable rows with keyboard-reachable Inspect buttons that report the stable id', () => {
 const onInspect = jest.fn();
 render(<BacktestTradeTable rows={rows} selectedId="b" onInspect={onInspect}/>);
 const table = screen.getByRole('table', {name: 'Closed trades'});
 expect(within(table).getAllByRole('columnheader').map(h => h.textContent)).toEqual(['Trade', 'Entry (UTC)', 'Exit (UTC)', 'Entry / exit price', 'Net return¹', 'Exit reason', 'On chart']);
 const second = screen.getByRole('button', {name: 'Inspect trade b'});
 second.focus();
 expect(second).toHaveFocus();
 fireEvent.click(second);
 expect(onInspect).toHaveBeenCalledWith('b');
 expect(second.closest('tr')).toHaveAttribute('aria-current', 'true');
 expect(screen.getByRole('button', {name: 'Inspect trade a'}).closest('tr')).not.toHaveAttribute('aria-current');
 expect(screen.getByText('43.13 / 39.88')).toBeInTheDocument();
 expect(screen.getByText('Time exit (holding limit)')).toBeInTheDocument();
});

it('passes each Inspect button to the caller for focus restoration', () => {
 const refs = new Map<string, HTMLButtonElement | null>();
 render(<BacktestTradeTable rows={rows} selectedId={null} onInspect={() => {}} inspectRef={(id, el) => refs.set(id, el)}/>);
 expect(refs.get('a')).toBe(screen.getByRole('button', {name: 'Inspect trade a'}));
});

it('states an empty table instead of rendering fabricated rows', () => {
 render(<BacktestTradeTable rows={[]} selectedId={null} onInspect={() => {}}/>);
 expect(screen.getByText('No closed trades recorded for this run.')).toBeInTheDocument();
 expect(screen.queryByRole('button')).not.toBeInTheDocument();
});
