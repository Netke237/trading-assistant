import '@testing-library/jest-dom';
import { render, screen, fireEvent } from '@testing-library/react';
import { StepNavBar } from '@/components/organisms/StepNavBar';
import { useScanStore } from '@/lib/scanStore';

const mockPush = jest.fn();
let mockPathname = '/screener/step-1-regime';

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush }),
  usePathname: () => mockPathname,
}));

describe('StepNavBar — Step 1 REJECT-gate race (H5)', () => {
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
});
