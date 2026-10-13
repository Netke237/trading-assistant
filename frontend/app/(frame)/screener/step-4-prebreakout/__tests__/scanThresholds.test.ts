import {fmtThreshold,truncPreBreakoutInts,truncFibInts,rememberScan,scanSnapshot} from '../scanThresholds';
import {PREBREAKOUT_DEFAULTS} from '@/components/organisms/PreBreakoutParamsPanel';
import {FIB_PULLBACK_DEFAULTS} from '@/components/organisms/FibPullbackParamsPanel';
test('applied integer overrides truncate toward zero and floats remain off-step',()=>{
 const p=truncPreBreakoutInts({...PREBREAKOUT_DEFAULTS,atrAvgLookback:23.9,rangeLookbackBars:-3.9,swingLookback:51.9,atrCompressionRatio:0.875});
 expect([p.atrAvgLookback,p.rangeLookbackBars,p.swingLookback,p.atrCompressionRatio]).toEqual([23,-3,51,0.875]);
 const original={...FIB_PULLBACK_DEFAULTS,fibSwingLookback:103.9,emaFilterPeriod:20.9};const fib=truncFibInts(original);original.fibLevels.push(50);expect(fib.fibLevels).toEqual([38.2,61.8]);original.fibLevels.pop();expect([fib.fibSwingLookback,fib.emaFilterPeriod]).toEqual([103,20]);
});
test('row array identity owns snapshots and unknown/replacement rows have none',()=>{
 const rows:unknown[]=[];const snapshot={scope:{mode:'prebreakout' as const,direction:'Bearish',horizon:'Swing',symbols:['AAA'],universe:undefined,runId:'run-A'}};rememberScan(rows,snapshot);expect(scanSnapshot(rows)).toBe(snapshot);expect(scanSnapshot([...rows])).toBeUndefined();
});
test('threshold text preserves bounded off-step precision',()=>{expect(fmtThreshold(.875,2)).toBe('0.875');expect(fmtThreshold(.0725*100,1)).toBe('7.25');expect(fmtThreshold(.0155*100,1)).toBe('1.55');});
