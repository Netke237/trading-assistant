import '@testing-library/jest-dom';
import { render, screen, fireEvent } from '@testing-library/react';
import { StepNavBar } from '@/components/organisms/StepNavBar';
import { PipelineInspector } from '@/components/organisms/PipelineInspector';
import { useScanStore } from '@/lib/scanStore';

const mockPush = jest.fn();
let mockPathname = '/screener/step-1-regime';

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush }),
  usePathname: () => mockPathname,
}));

describe('StepNavBar — Step 1 REJECT-gate race (H5)', () => {
  it('keeps both arrows inside the pipeline drawer and restores navigation after close', () => {
    mockPush.mockClear();
    mockPathname = '/screener/step-4-ranking';
    useScanStore.setState({ combinedRegime: 'PASS', screenerMode: 'options' });
    const { rerender } = render(<><StepNavBar /><PipelineInspector onClose={() => {}} /></>);
    const copy = screen.getByRole('button', { name: 'Copy Tree' });
    copy.focus();
    fireEvent.keyDown(copy, { key: 'ArrowLeft' });
    fireEvent.keyDown(copy, { key: 'ArrowRight' });
    fireEvent.click(screen.getByRole('button', { name: 'Plaintext Tree' }));
    fireEvent.keyDown(screen.getByRole('button', { name: 'Plaintext Tree' }), { key: 'ArrowRight' });
    fireEvent.keyDown(window, { key: 'ArrowLeft' });
    expect(mockPush).not.toHaveBeenCalled();
    rerender(<><StepNavBar /><PipelineInspector isOpen={false} onClose={() => {}} /></>);
    fireEvent.keyDown(window, { key: 'ArrowRight' });
    expect(mockPush).toHaveBeenCalledWith('/screener/step-5-vol-events');
  });
  beforeEach(() => {
    mockPush.mockClear();
    mockPathname = '/screener/step-1-regime';
    useScanStore.setState({ combinedRegime: 'PENDING', screenerMode: 'options' } as any);
  });

  it('disables Next on step 1 while combinedRegime is PENDING', () => {
    render(<StepNavBar />);
    const nextBtn = screen.getByRole('button', { name: /next/i });
    expect(nextBtn).toBeDisabled();

    fireEvent.click(nextBtn);
    expect(mockPush).not.toHaveBeenCalled();
  });

  it('enables Next on step 1 once combinedRegime resolves to PASS', () => {
    useScanStore.setState({ combinedRegime: 'PASS' } as any);
    render(<StepNavBar />);
    const nextBtn = screen.getByRole('button', { name: /next/i });
    expect(nextBtn).not.toBeDisabled();

    fireEvent.click(nextBtn);
    expect(mockPush).toHaveBeenCalledWith('/screener/step-2-universe');
  });

  it('shows the REJECT confirm dialog once combinedRegime resolves to REJECT', () => {
    useScanStore.setState({ combinedRegime: 'REJECT' } as any);
    render(<StepNavBar />);
    fireEvent.click(screen.getByRole('button', { name: /next/i }));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(mockPush).not.toHaveBeenCalled();
  });

  it('ArrowRight key does not advance while regime is PENDING', () => {
    render(<StepNavBar />);
    fireEvent.keyDown(window, { key: 'ArrowRight' });
    expect(mockPush).not.toHaveBeenCalled();
  });

  it('ArrowRight key advances once regime resolves to PASS', () => {
    useScanStore.setState({ combinedRegime: 'PASS' } as any);
    render(<StepNavBar />);
    fireEvent.keyDown(window, { key: 'ArrowRight' });
    expect(mockPush).toHaveBeenCalledWith('/screener/step-2-universe');
  });

  it('does not gate Next on PENDING regime for steps other than step 1', () => {
    mockPathname = '/screener/step-2-universe';
    render(<StepNavBar />);
    const nextBtn = screen.getByRole('button', { name: /next/i });
    expect(nextBtn).not.toBeDisabled();
  });

  it('ArrowRight key does not advance when a <select> element has focus', () => {
    useScanStore.setState({ combinedRegime: 'PASS' } as any);
    render(
      <>
        <StepNavBar />
        <select data-testid="horizon-select">
          <option value="swing">Swing</option>
          <option value="position">Position</option>
        </select>
      </>,
    );
    const select = screen.getByTestId('horizon-select');
    select.focus();
    fireEvent.keyDown(select, { key: 'ArrowRight' });
    expect(mockPush).not.toHaveBeenCalled();
  });
});
