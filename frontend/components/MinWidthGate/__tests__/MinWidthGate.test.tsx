import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { MinWidthGate } from '..';

let mockPathname = '/screener/step-7-trade-card';
jest.mock('next/navigation', () => ({ usePathname: () => mockPathname }));
let width = 1200;
const queries: { query: string; listeners: Set<() => void> }[] = [];

beforeEach(() => {
  width = 1200;
  mockPathname = '/screener/step-7-trade-card';
  queries.length = 0;
  Object.defineProperty(window, 'innerWidth', { configurable: true, get: () => width });
  window.matchMedia = jest.fn((query: string) => {
    const listeners = new Set<() => void>();
    queries.push({ query, listeners });
    return {
      media: query,
      get matches() { return width <= Number(/max-width: (\d+)px/.exec(query)?.[1]); },
      addEventListener: (_event: string, listener: () => void) => listeners.add(listener),
      removeEventListener: (_event: string, listener: () => void) => listeners.delete(listener),
    } as unknown as MediaQueryList;
  });
});

it('allows the real Step 7 at the1200 boundary', () => {
  render(<MinWidthGate><div>Trade card</div></MinWidthGate>);
  expect(screen.queryByRole('dialog', { name: 'Desktop required' })).not.toBeInTheDocument();
  expect(window.matchMedia).toHaveBeenCalledWith('(max-width: 1199px)');
});

it('retains the Step 7 guard below1200 with its actual minimum in the explanation', () => {
  width = 1199;
  render(<MinWidthGate><div>Trade card</div></MinWidthGate>);
  expect(screen.getByRole('dialog', { name: 'Desktop required' })).toHaveTextContent('1200 pixels wide');
});

it.each(['/settings', '/dashboard', '/screener/step-6-contracts'])('keeps1280 on %s', (path) => {
  mockPathname = path;
  render(<MinWidthGate><div>Other route</div></MinWidthGate>);
  expect(screen.getByRole('dialog', { name: 'Desktop required' })).toHaveTextContent('1280 pixels wide');
  expect(window.matchMedia).toHaveBeenCalledWith('(max-width: 1279px)');
});

it('rebinds the route-specific boundary and preserves one stateful child across overlays', () => {
  width = 1250;
  const child = <input aria-label="Retained control" defaultValue="planned" />;
  const { rerender, unmount } = render(<MinWidthGate>{child}</MinWidthGate>);
  const input = screen.getByRole('textbox', { name: 'Retained control' });
  fireEvent.change(input, { target: { value: 'edited' } });
  mockPathname = '/settings';
  rerender(<MinWidthGate>{child}</MinWidthGate>);
  expect(screen.getByRole('dialog', { name: 'Desktop required' })).toHaveTextContent('1280 pixels wide');
  expect(queries[0].listeners.size).toBe(0);
  expect(screen.getByRole('textbox', { name: 'Retained control' })).toBe(input);
  expect(input).toHaveValue('edited');
  mockPathname = '/screener/step-7-trade-card';
  rerender(<MinWidthGate>{child}</MinWidthGate>);
  expect(screen.queryByRole('dialog', { name: 'Desktop required' })).not.toBeInTheDocument();
  expect(queries[1].listeners.size).toBe(0);
  expect(input).toHaveValue('edited');
  act(() => { width = 1199; queries[2].listeners.forEach(fn => fn()); });
  expect(screen.getByRole('dialog', { name: 'Desktop required' })).toBeInTheDocument();
  act(() => { width = 1200; queries[2].listeners.forEach(fn => fn()); });
  expect(screen.queryByRole('dialog', { name: 'Desktop required' })).not.toBeInTheDocument();
  expect(screen.getByRole('textbox', { name: 'Retained control' })).toBe(input);
  unmount();
  expect(queries.every(q => q.listeners.size === 0)).toBe(true);
});

it('allows Position at 1200 and keeps its edited child mounted across resize and route changes', () => {
  mockPathname = '/screener/step-7-position-card';
  const child = <input aria-label="Position shares" defaultValue="30" />;
  const view = render(<MinWidthGate>{child}</MinWidthGate>);
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(window.matchMedia).toHaveBeenCalledWith('(max-width: 1199px)');
  const control = screen.getByRole('textbox', { name: 'Position shares' });
  fireEvent.change(control, { target: { value: '50' } });
  act(() => { width = 1199; queries[0].listeners.forEach(fn => fn()); });
  expect(screen.getByRole('dialog')).toHaveTextContent('1200 pixels wide');
  expect(control).toHaveValue('50');
  act(() => { width = 1200; queries[0].listeners.forEach(fn => fn()); });
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  mockPathname = '/dashboard';
  view.rerender(<MinWidthGate>{child}</MinWidthGate>);
  expect(screen.getByRole('dialog')).toHaveTextContent('1280 pixels wide');
  expect(queries[0].listeners.size).toBe(0);
  mockPathname = '/screener/step-7-position-card';
  view.rerender(<MinWidthGate>{child}</MinWidthGate>);
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(screen.getByRole('textbox')).toBe(control);
  expect(control).toHaveValue('50');
  expect(queries[1].listeners.size).toBe(0);
  view.unmount();
  expect(queries.every(q => q.listeners.size === 0)).toBe(true);
});
