import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import Page from '../page';
import { api } from '@/lib/api';
import { useScanStore } from '@/lib/scanStore';
import { useUniverseStore } from '@/lib/universeStore';
jest.mock('@/lib/api',()=>({api:{getLatestScanReport:jest.fn().mockImplementation((category:string)=>Promise.resolve({category,latest_attempt:null,previous_report:null})),postStockScan:jest.fn(),prebreakoutScan:jest.fn(),fibPullbackScan:jest.fn()}}));
jest.mock('@/components/organisms/CompositeAlertDialog',()=>({CompositeAlertDialog:()=>null}));
test('Pullback captures explicit category at dispatch even when sub-mode switches before completion',async()=>{
 useUniverseStore.setState({pick:'SP500'});useScanStore.setState({preBreakoutResults:[],fibPullbackResults:[],context:null});
 let resolve!:(x:unknown)=>void;(api.postStockScan as jest.Mock).mockImplementation(()=>new Promise(r=>{resolve=r;}));
 render(<Page/>);await screen.findByText('No saved report available.');
 expect(api.postStockScan).not.toHaveBeenCalled();expect(api.prebreakoutScan).not.toHaveBeenCalled();
 fireEvent.click(screen.getByRole('button',{name:/Pullback to EMA/}));fireEvent.click(screen.getByRole('button',{name:'Run Scan'}));
 await waitFor(()=>expect(api.postStockScan).toHaveBeenCalledWith(expect.objectContaining({category:'pullback',strategy:'pullback_ema'})));
 fireEvent.click(screen.getByRole('button',{name:'Fib Pullback'}));
 await act(async()=>{resolve({candidates:[],report_run_id:'pullback-D'});});
 expect(screen.getByLabelText('Report category')).toHaveValue('fib');expect(api.fibPullbackScan).not.toHaveBeenCalled();
});
