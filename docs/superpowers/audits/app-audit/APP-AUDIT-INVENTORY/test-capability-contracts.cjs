/* Regression: omissions must fail even when cardinality or legacy checks still look valid. */
const assert=require('assert/strict'),fs=require('fs'),path=require('path');
const read=f=>JSON.parse(fs.readFileSync(path.join(__dirname,f),'utf8'));
const i=read('inventory.json'),s=read('semantic-classification.json'),o=read('supplemental-capability-contracts.json'),verify=require('./verify-capability-contracts.cjs');
verify(i,s,o);
assert.equal(o.capability_state_contracts.length,4);
for(const name of ['ContractScoreExplanation','IndicatorPanel','ChartOverlays','DrawingOverlays']) assert(o.capability_state_contracts.some(c=>c.capability_id.endsWith('#'+name)));
const mutants=[
 ['missing contract',(_s,o)=>o.capability_state_contracts.pop()],
 ['missing reachable route',(_s,o)=>o.route_instances.pop()],
 ['lost route/state reference',(_s,o)=>o.route_state_requirements.pop()],
 ['missing branch despite nine base states',(_s,o)=>{const c=o.capability_state_contracts.find(c=>c.capability_id.endsWith('#ChartOverlays'));c.states=c.states.filter(s=>s.key!=='kind-FVG-hidden');}],
 ['unresolved native owner',(s)=>{s.jsx_occurrences.find(j=>j.kind==='native').parent_definition_id=null;}],
 ['lost native state ref',(s)=>{delete s.jsx_occurrences.find(j=>j.state_contract_ref).state_contract_ref;}],
 ['lost HOC inheritance',(_s,o)=>{o.capability_state_contracts.find(c=>c.capability_id.endsWith('#ContractScoreExplanation')).states[0].inheritance.definition_id='missing';}],
 ['lost caller binding',(s)=>{s.supplemental_local_capabilities[0].entry_call_ids[0]='missing';}],
 ['wrong combined route owner',(_s,o)=>{o.route_state_requirements[0].owners.numeric_lanes=['A'];}]
];
for(const [name,mutate] of mutants){const ms=structuredClone(s),mo=structuredClone(o);mutate(ms,mo);assert.throws(()=>verify(i,ms,mo),undefined,name);}
console.log(JSON.stringify({passed:true,omission_checks:mutants.length}));
