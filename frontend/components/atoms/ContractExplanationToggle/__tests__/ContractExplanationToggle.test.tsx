import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { ContractExplanationToggle } from '../index';

describe('ContractExplanationToggle atom', () => {
  test('renders with accessible attributes', () => {
    render(
      <ContractExplanationToggle
        isOpen={false}
        onToggle={jest.fn()}
        controlsId="exp-aapl-185"
        contractLabel="AAPL 185C 05/16"
      />
    );
    const btn = screen.getByRole('button', { name: /explain score for aapl 185c 05\/16/i });
    expect(btn).toBeInTheDocument();
    expect(btn).toHaveAttribute('aria-expanded', 'false');
    expect(btn).toHaveAttribute('aria-controls', 'exp-aapl-185');
    expect(screen.getByText('Explain')).toBeInTheDocument();
  });

  test('toggles to Hide and aria-expanded=true when open', () => {
    render(
      <ContractExplanationToggle
        isOpen={true}
        onToggle={jest.fn()}
        controlsId="exp-aapl-185"
        contractLabel="AAPL 185C 05/16"
      />
    );
    const btn = screen.getByRole('button', { name: /hide score explanation for aapl 185c 05\/16/i });
    expect(btn).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('Hide')).toBeInTheDocument();
  });

  test('stops propagation on click to avoid selecting table row', () => {
    const onToggle = jest.fn();
    const parentClick = jest.fn();

    render(
      <div onClick={parentClick}>
        <ContractExplanationToggle
          isOpen={false}
          onToggle={onToggle}
          controlsId="exp-aapl-185"
          contractLabel="AAPL 185C 05/16"
        />
      </div>
    );

    const btn = screen.getByRole('button');
    fireEvent.click(btn);

    expect(onToggle).toHaveBeenCalledTimes(1);
    expect(parentClick).not.toHaveBeenCalled();
  });

  test('stops propagation on Space and Enter keydown', () => {
    const onToggle = jest.fn();
    const parentKeyDown = jest.fn();

    render(
      <div onKeyDown={parentKeyDown}>
        <ContractExplanationToggle
          isOpen={false}
          onToggle={onToggle}
          controlsId="exp-aapl-185"
          contractLabel="AAPL 185C 05/16"
        />
      </div>
    );

    const btn = screen.getByRole('button');
    fireEvent.keyDown(btn, { key: 'Enter' });
    expect(parentKeyDown).not.toHaveBeenCalled();

    fireEvent.keyDown(btn, { key: ' ' });
    expect(parentKeyDown).not.toHaveBeenCalled();
  });
});
