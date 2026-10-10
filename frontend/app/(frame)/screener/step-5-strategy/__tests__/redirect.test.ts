import { redirect } from 'next/navigation';
import Step5Redirect from '../page';
jest.mock('next/navigation', () => ({ redirect: jest.fn() }));

it('sends the retired Step 5 URL to the Stocks strategy step', () => {
  Step5Redirect();
  expect(redirect).toHaveBeenCalledWith('/screener/step-4-stocks');
});
