import {act,fireEvent,render,screen} from '@testing-library/react';
import FreshBacktestControls from '.';
import {api} from '@/lib/api';

jest.mock('@/lib/api',()=>({api:{getFreshBacktestConfiguration:jest.fn(),runFreshBacktest:jest.fn()}}));
const configuration={strategies:['pullback_ema'],parameters:{pullback_ema:{ema_period:'int'}},multi_fields:[]};
beforeEach(()=>{jest.clearAllMocks();(api.getFreshBacktestConfiguration as jest.Mock).mockResolvedValue(configuration);});
async function configure(){
 fireEvent.click(screen.getByRole('button',{name:'Configure a fresh run'}));
 await act(async()=>{});
 fireEvent.change(screen.getByLabelText('Fresh strategy'),{target:{value:'pullback_ema'}});
 fireEvent.change(screen.getByLabelText('Fresh direction'),{target:{value:'Bearish'}});
 fireEvent.change(screen.getByLabelText('Evaluation start'),{target:{value:'2024-01-01'}});
 fireEvent.change(screen.getByLabelText('Evaluation end (exclusive)'),{target:{value:'2024-12-31'}});
 fireEvent.change(screen.getByLabelText('Commission per leg (fraction)'),{target:{value:'0.002'}});
 fireEvent.change(screen.getByLabelText('Maximum hold days (null for none)'),{target:{value:'10'}});
 fireEvent.change(screen.getByLabelText('Minimum closed trades'),{target:{value:'5'}});
 fireEvent.change(screen.getByLabelText('Minimum win rate (fraction)'),{target:{value:'0.5'}});
 fireEvent.change(screen.getByLabelText('Complete strategy parameters (JSON)'),{target:{value:'{"ema_period":50}'}});
 fireEvent.click(screen.getByLabelText(/I reviewed the strategy/));
}

test('unknown original settings are blank; explicit configuration sends distinct fresh request',async()=>{
 const accept=jest.fn();
 (api.runFreshBacktest as jest.Mock).mockImplementation(async request=>({status:'success',artifact:{schema_version:1,artifact_id:'fresh-id',provenance:'fresh',identity:{symbol:'AAA',strategy:request.strategy,direction:request.direction,interval:'1d'},detail:{status:'success',effective_params:request.params,configuration:{...request,entry_start:request.start,entry_end:request.end}}}}));
 render(<FreshBacktestControls symbol="AAA" original={null} onResult={accept}/>);
 fireEvent.click(screen.getByRole('button',{name:'Configure a fresh run'}));await act(async()=>{});
 expect(screen.getByLabelText('Fresh strategy')).toHaveValue('');
 expect(screen.getByLabelText('Fresh direction')).toHaveValue('');
 expect(screen.getByLabelText('Commission per leg (fraction)')).toHaveValue(null);
 fireEvent.click(screen.getByRole('button',{name:'Close configuration'}));
 await configure();
 fireEvent.click(screen.getByRole('button',{name:'Run fresh backtest'}));await act(async()=>{});
 expect(api.runFreshBacktest).toHaveBeenCalledWith(expect.objectContaining({symbol:'AAA',direction:'Bearish',strategy:'pullback_ema',commission:.002,start:'2024-01-01',end:'2024-12-31',initial_cash:100000,order_size:.9999999999999998,confirmed:true}),expect.any(AbortSignal));
 expect(accept).toHaveBeenCalledWith(expect.objectContaining({provenance:'fresh'}));
});

test('cancelled and stale requests cannot display results or overwrite original',async()=>{
 const accept=jest.fn();let resolve!:(v:unknown)=>void;
 (api.runFreshBacktest as jest.Mock).mockImplementation(()=>new Promise(r=>{resolve=r;}));
 const view=render(<FreshBacktestControls symbol="AAA" original={null} onResult={accept}/>);
 await configure();fireEvent.click(screen.getByRole('button',{name:'Run fresh backtest'}));
 const signal=(api.runFreshBacktest as jest.Mock).mock.calls[0][1];
 fireEvent.click(screen.getByRole('button',{name:'Cancel fresh run'}));
 expect(signal.aborted).toBe(true);
 view.rerender(<FreshBacktestControls symbol="BBB" original={null} onResult={accept}/>);
 await act(async()=>resolve({status:'success',artifact:{provenance:'fresh',identity:{symbol:'AAA'},detail:{status:'success'}}}));
 expect(accept).not.toHaveBeenCalled();
});

test('failure is explicit and does not replace original',async()=>{
 const accept=jest.fn();(api.runFreshBacktest as jest.Mock).mockResolvedValue({status:'insufficient_history',artifact:null});
 render(<FreshBacktestControls symbol="AAA" original={null} onResult={accept}/>);
 await configure();fireEvent.click(screen.getByRole('button',{name:'Run fresh backtest'}));await act(async()=>{});
 expect(screen.getByRole('status')).toHaveTextContent('Fresh run unavailable: insufficient_history');
 expect(accept).not.toHaveBeenCalled();
});


test.each(['direction','strategy','params','commission','window','sizing'])('rejects mismatched fresh %s',async mismatch=>{
 const accept=jest.fn();
 (api.runFreshBacktest as jest.Mock).mockImplementation(async request=>{
  const artifact={schema_version:1,artifact_id:'fresh-id',provenance:'fresh',identity:{symbol:'AAA',strategy:request.strategy,direction:request.direction,interval:'1d'},detail:{status:'success',effective_params:request.params,configuration:{...request,entry_start:request.start,entry_end:request.end}}};
  if(mismatch==='direction')artifact.identity.direction='Bullish';
  if(mismatch==='strategy')artifact.identity.strategy='breakout_base';
  if(mismatch==='params')artifact.detail.effective_params={ema_period:1};
  if(mismatch==='commission')artifact.detail.configuration.commission=.1;
  if(mismatch==='window')artifact.detail.configuration.entry_start='2024-02-01';
  if(mismatch==='sizing')artifact.detail.configuration.order_size=.5;
  return {status:'success',artifact};
 });
 render(<FreshBacktestControls symbol="AAA" original={null} onResult={accept}/>);
 await configure();fireEvent.click(screen.getByRole('button',{name:'Run fresh backtest'}));await act(async()=>{});
 expect(screen.getByRole('status')).toHaveTextContent('Fresh run unavailable: invalid_evidence');
 expect(accept).not.toHaveBeenCalled();
});
