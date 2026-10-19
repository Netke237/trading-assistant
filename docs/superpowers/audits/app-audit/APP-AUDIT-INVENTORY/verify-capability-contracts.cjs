const assert = require('assert/strict');
function verify(i, semantic, overlay) {
  assert(overlay, 'supplemental capability route/state contracts missing');
  assert.equal(overlay.source_baseline, i.source_baseline);
  const caps = new Map(semantic.supplemental_local_capabilities.map(c => [c.id,c]));
  const contracts = new Map(overlay.capability_state_contracts.map(c => [c.capability_id,c]));
  assert.equal(contracts.size,caps.size,'every supplemental capability needs a contract');
  const calls = new Map(semantic.jsx_occurrences.map(j=>[j.id,j]));
  const stateIds = new Set();
  for (const [id,cap] of caps) {
    const contract=contracts.get(id); assert(contract,'missing capability contract '+id);
    assert.deepEqual(contract.source_range,{source:cap.source,line:cap.line,end_line:cap.end_line});
    assert.deepEqual(contract.entry_call_ids,cap.entry_call_ids);
    assert.equal(cap.state_contract_ref,'supplemental-capability-contracts.json#'+id);
    for(const range of [contract.source_range,...contract.supporting_source_ranges]) {
      const file=require('path').join(__dirname,'../../../../..',range.source);
      assert(range.line>0&&range.end_line>=range.line&&range.end_line<=require('fs').readFileSync(file,'utf8').split(/\r?\n/).length,'invalid supplemental source range');
    }
    for(const key of i.state_matrix_templates['conservative-nine-state-v1'].map(s=>s.key)) assert(contract.states.some(s=>s.key===key),'missing state '+key);
    for(const s of contract.states) {
      assert(!stateIds.has(s.id),'duplicate capability state'); stateIds.add(s.id);
      assert(s.id===id+'/state:'+s.key);
      assert(s.fixture_contract&&s.source_evidence.length&&s.correctness_status==='pending owning lane');
      assert(s.owners.numeric_lanes.length&&s.owners.persistence==='I'&&s.owners.presentation==='J');
      for(const evidence of s.source_evidence) assert(evidence.source&&evidence.line&&evidence.end_line>=evidence.line);
    }
    assert(cap.entry_call_ids.every(cid=>calls.has(cid)),'lost caller reference');
  }
  const expected=[];
  for(const route of semantic.route_symbol_classification) for(const id of route.jsx_reachable_capability_ids.filter(id=>caps.has(id))) expected.push(route.route_entry_id+'::'+id);
  assert.deepEqual(overlay.route_instances.map(r=>r.id).sort(),expected.sort(),'reachable capability missing route instance');
  const rows=new Map(overlay.route_state_requirements.map(r=>[r.id,r]));
  assert.equal(rows.size,overlay.route_state_requirements.length);
  for(const instance of overlay.route_instances) {
    const contract=contracts.get(instance.capability_id);
    assert.equal(instance.state_requirement_ids.length,contract.states.length);
    for(const s of contract.states) {
      const row=rows.get(instance.id+'/state:'+s.key); assert(row,'missing route/state requirement');
      assert(instance.state_requirement_ids.includes(row.id));
      assert.equal(row.capability_state_id,s.id); assert.equal(row.route_instance_id,instance.id);
      assert.equal(row.route_entry_id,instance.route_entry_id);
      assert.deepEqual(row.owners.numeric_lanes,[...new Set([...contract.owners.numeric_lanes,i.route_entries.find(e=>e.id===instance.route_entry_id).owners.numeric])].sort());
      assert.equal(row.fixture_contract_ref,s.id);
    }
  }
  assert.equal(rows.size,overlay.route_instances.reduce((n,r)=>n+r.state_requirement_ids.length,0),'orphan route state');
  for(const j of semantic.jsx_occurrences.filter(j=>j.kind==='native')) {
    assert(j.parent_definition_id,'unresolved native owner contract '+j.id);
    if(caps.has(j.parent_definition_id)) {
      const native=overlay.native_state_inheritance.find(n=>n.jsx_id===j.id); assert(native,'native supplemental state inheritance missing');
      assert.deepEqual(native.state_ids,contracts.get(j.parent_definition_id).states.map(s=>s.id));
    }
  }
  const root=require('path').resolve(__dirname,'../../../../..');
  assert.deepEqual(overlay,require('./capability-contracts.cjs')(i,semantic,root),'generated supplemental contracts/fixture/source references drift');
  const defs=new Map(i.definitions.map(d=>[d.id,d]));
  for(const c of contracts.values()) for(const s of c.states) {
    for(const ref of s.caller_state_refs) assert(defs.has(ref.definition_id)&&i.state_matrix_templates['conservative-nine-state-v1'].some(t=>t.key===ref.state_key),'lost inherited caller state');
    if(typeof s.inheritance==='object') assert(defs.has(s.inheritance.definition_id)&&i.state_matrix_templates['conservative-nine-state-v1'].some(t=>t.key===s.inheritance.state_key),'lost HOC state inheritance');
  }
  for(const j of semantic.jsx_occurrences.filter(j=>j.kind==='native')) {
    assert(defs.has(j.parent_definition_id)||caps.has(j.parent_definition_id),'lost native contract owner');
    if(j.entry_context.helper||caps.has(j.parent_definition_id)) assert.equal(j.state_contract_ref,j.parent_definition_id,'lost native state reference');
  }
  return true;
}
module.exports=verify;
if(require.main===module) {
 const fs=require('fs'),path=require('path'),read=f=>JSON.parse(fs.readFileSync(path.join(__dirname,f),'utf8'));
 const file=path.join(__dirname,'supplemental-capability-contracts.json');
 verify(read('inventory.json'),read('semantic-classification.json'),fs.existsSync(file)?read('supplemental-capability-contracts.json'):null);
 console.log('supplemental capability contracts validated');
}
