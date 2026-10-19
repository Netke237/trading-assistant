// Audit-only probes of real source in Node, with in-memory storage and no fetch.
const fs=require('fs'),path=require('path'),Module=require('module'),crypto=require('crypto');
const root=path.resolve(__dirname,'../../../../../..'),front=path.join(root,'frontend');
require(path.join(front,'node_modules/ts-node')).register({transpileOnly:true,compilerOptions:{module:'CommonJS',moduleResolution:'node',target:'ES2020',jsx:'react-jsx',esModuleInterop:true}});
const resolve=Module._resolveFilename;Module._resolveFilename=function(n,...a){return resolve.call(this,n.startsWith('@/')?path.join(front,n.slice(2)):n,...a)};
const mem=new Map();global.localStorage={getItem:k=>mem.get(k)??null,setItem:(k,v)=>mem.set(k,v),removeItem:k=>mem.delete(k)};global.window={localStorage:global.localStorage};global.fetch=()=>{throw Error('Network forbidden by audit harness')};
const {api}=require(path.join(front,'lib/api.ts'));api.getScanSchedule=async()=>[];
const {useScanStore:s}=require(path.join(front,'lib/scanStore.ts')),{useUniverseStore:u}=require(path.join(front,'lib/universeStore.ts')),{useSettingsStore:t}=require(path.join(front,'lib/settingsStore.ts')),{useScanParamsStore:sp}=require(path.join(front,'lib/scanParamsStore.ts')),{useSearchProfilesStore:ps}=require(path.join(front,'lib/searchProfilesStore.ts'));
const {captureCurrentSnapshot,applySearchProfile}=require(path.join(front,'lib/searchProfileSnapshot.ts')),{resolveProfileToScanRequest}=require(path.join(front,'lib/scanScheduleResolve.ts'));
const pack=JSON.parse(fs.readFileSync(path.join(root,'docs/search-profiles/search-profiles-export.json'))),base=pack.state.profiles[0],out={mocked:'in-memory browser storage; API getScanSchedule returns []; fetch forbidden',checks:[],payloads:[],hashes:{}};
const clone=x=>JSON.parse(JSON.stringify(x));function check(id,expected,actual){out.checks.push({id,status:JSON.stringify(expected)===JSON.stringify(actual)?'pass':'fail',expected,actual})}
// Follow-up inventory and request observations; does not repeat lifecycle checks.
(async()=>{out.provenance={source:'880c8441841cc22d5090cdc5f984e4cf7e3d9a8d',boundary:'real frontend stores and pure request builders; in-memory storage; no backend or provider request'};
const defs=JSON.parse(fs.readFileSync(path.join(__dirname,'source-output.json'))).paramDefinitions;
const {PARAM_DEFAULTS_PER_HORIZON:defaults}=require(path.join(front,'lib/executionParamDefaults.ts'));
const {SCAN_PARAM_DEFAULTS}=require(path.join(front,'lib/scanParamsStore.ts'));
out.defaults=defaults;out.matrix=[];
const top=new Set(['min_stock_score','confidence_caution_below','confidence_reject_below','confidence_atr_mult_target','confidence_atr_mult_stop','regime_headwind_caution_pct','regime_headwind_reject_pct','fundamentals_caution_above','fundamentals_reject_above','pullback_require_reversal']);
function locate(r,key){if(Object.prototype.hasOwnProperty.call(r,key))return {location:key,value:r[key]};if(Object.prototype.hasOwnProperty.call(r.overrides||{},key))return {location:'overrides.'+key,value:r.overrides[key]};return {location:'absent'};}
for(const def of defs){const row={...def,defaults:Object.fromEntries(Object.entries(defaults).map(([h,d])=>[h,d[def.key]??null])),observations:[]};
if(def.type==='display'||def.deprecated||def.redundant){row.scope='display only; no direct edit';out.matrix.push(row);continue;}
const custom=def.type==='select'?def.options.at(-1):def.type==='boolean'?true:(def.min+(def.max-def.min)/3);
const cases=def.type==='number'?[['absent',undefined],['null',null],['zero',0],['minimum',def.min],['maximum',def.max],['custom',custom]]:def.type==='boolean'?[['absent',undefined],['null',null],['false',false],['custom',true]]:[['absent',undefined],['null',null],...def.options.map(x=>[x,x])];
for(const mode of ['options','stocks'])for(const [kind,value]of cases){const profile={...clone(base),mode,strategy:'pullback_ema',strategyParams:{...SCAN_PARAM_DEFAULTS},scanOverrides:{}};if(kind!=='absent')profile.scanOverrides[def.key]=value;const request=resolveProfileToScanRequest(profile);row.observations.push({mode,kind,input:kind==='absent'?'absent':value,request:locate(request,def.key)});}
applySearchProfile({...clone(base),mode:'options',scanOverrides:{[def.key]:custom}});const saved=captureCurrentSnapshot('options');check('snapshot preserves '+def.key,custom,saved.scanOverrides[def.key]);row.storeAndSnapshot=saved.scanOverrides[def.key];out.matrix.push(row);}
for(const key of ['confidence_caution_below','confidence_reject_below']){const profile={...clone(base),mode:'stocks',strategy:'pullback_ema',strategyParams:{...SCAN_PARAM_DEFAULTS},scanOverrides:{[key]:0}};const r=resolveProfileToScanRequest(profile);check('stocks panel '+key+' effective zero',0,r[key]);out.payloads.push({id:'stocks-panel-'+key,profile,request:r});}
const er={...clone(base),scanOverrides:{entry_min_premium:5,entry_max_slippage_pct:0,entry_spread_tolerance_pct:0}};out.payloads.push({id:'entry-quality-knobs',request:resolveProfileToScanRequest(er)});
const wr={...clone(base),scanOverrides:{weight_trend:40}};out.payloads.push({id:'percent-weight',request:resolveProfileToScanRequest(wr)});
check('inventory definitions',66,out.matrix.length);
})().catch(e=>{out.fatal=e.message;process.exitCode=1}).finally(()=>{fs.writeFileSync(path.join(__dirname,'parameter-output.json'),JSON.stringify(out,null,2)+'\n');console.log(JSON.stringify({checks:out.checks.length,failed:out.checks.filter(x=>x.status==='fail').map(x=>x.id),fatal:out.fatal}));});
