/* Focused, read-only checks of the report contract and known application edge cases. */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '../../../../..');
const inventory = JSON.parse(fs.readFileSync(path.join(__dirname, 'inventory.json')));
const provenance = JSON.parse(fs.readFileSync(path.join(__dirname, 'provenance.json')));
function files(dir) {
  return fs.readdirSync(dir, {withFileTypes: true}).flatMap(e =>
    e.isDirectory() ? files(path.join(dir,e.name)) : [path.join(dir,e.name)]);
}
const census = files(path.join(root,'frontend/app')).filter(f =>
  /[\\/](page|layout|default|loading|error|not-found)\.tsx$/.test(f) && !f.includes('__tests__'))
  .map(f => path.relative(root,f).replaceAll('\\','/')).sort();
assert.deepEqual(inventory.route_entries.map(e=>e.source).sort(),census);
assert.equal(census.length,45);
const route = suffix => inventory.route_entries.find(e=>e.source.endsWith(suffix));
assert.equal(route('/app/page.tsx').classification,'redirect');
assert(route('/app/page.tsx').navigation.some(e=>e.call === "redirect('/dashboard')"));
assert.equal(route('/__test-crash/page.tsx').classification,'private-folder-source');
assert.equal(route('/dev/components/page.tsx').exposure.includes('development'),true);
assert.equal(route('/step-5-strategy/page.tsx').classification,'redirect');
assert(route('/step-5-strategy/page.tsx').navigation.some(e=>e.call.includes('/screener/step-4-stocks')));
const standalone=route('/chart/standalone/page.tsx');
assert(standalone.attached_entry_sources.includes('frontend/app/layout.tsx'));
assert(!standalone.attached_entry_sources.includes('frontend/app/(frame)/layout.tsx'));
const analysis=route('/(frame)/analysis/page.tsx');
assert(analysis.attached_entry_sources.includes('frontend/app/(frame)/@contextRail/analysis/page.tsx'));
const defs=new Map(inventory.definitions.map(d=>[d.id,d]));
const native=inventory.definitions.flatMap(d=>d.native_surfaces);
assert.equal(new Set(native.map(n=>n.id)).size,native.length);
assert(native.some(n=>n.id.endsWith('::portal:methodSelector')));
assert(native.some(n=>n.id.endsWith('::imperative:drawing-events')));
assert(native.some(n=>n.source.includes('/Tooltip/')&&n.categories.includes('tooltip-or-description')));
for(const n of native){
  assert(defs.has(n.parent_definition_id));
  assert(n.line>0&&n.owners.numeric&&n.owners.persistence==='I'&&n.owners.presentation==='J');
  assert(n.entry_action&&n.runtime_status==='pending');
}
const settings=new Set(inventory.settings_sections.map(s=>s.key));
assert.deepEqual([...settings].sort(),['theme','scan','strategy','brokers','risk','regime','notifications','data','tuning'].sort());
for(const section of inventory.settings_sections)assert(inventory.definitions.some(d=>d.source===section.source&&d.component===section.component));
assert(inventory.definitions.some(d=>d.component==='StoreHydration'));
assert(inventory.definitions.some(d=>d.component==='InitStores'));
const states=inventory.state_matrix_templates['conservative-nine-state-v1'];
assert.equal(states.length,9);assert(states.every(s=>s.status==='pending'));
let nativeInstances=0;
for(const i of inventory.route_instances){
  assert(defs.has(i.definition_id));assert.equal(i.state_ids.length,9);
  assert(i.state_ids.every((id,k)=>id===i.id+'::state:'+states[k].key));
  nativeInstances+=defs.get(i.definition_id).native_surfaces.length;
}
assert.equal(inventory.counts.native_route_requirement_instances_normalized,nativeInstances);
assert.equal(inventory.counts.native_state_requirement_ids_normalized,nativeInstances*9);
assert(provenance.source_and_config_hashes.some(h=>h.source==='frontend/components/atoms/Tooltip/Tooltip.module.css'));
assert.equal(inventory.completion_claim,false);
assert(inventory.pending_discovery.some(p=>p.id==='pending:semantic-closure'));
console.log('PASS: independent filesystem census, redirects/private route, slot/standalone roots, native identities, portal/imperative/CSS fixtures, Settings components, lifecycle definitions and normalized state joins.');
