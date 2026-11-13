'use strict';
const {test}=require('node:test');const assert=require('node:assert/strict');
const {loadFrozen,BASELINE,sha,json}=require('../map-common.cjs');
const {generateSourceMap}=require('../source-map.cjs');const {generateTargetMap}=require('../target-map.cjs');
test('real git-show inputs preserve historical ids, current mixed-module contexts, hashes and byte reproducibility',()=>{
 const input=loadFrozen();assert.equal(input.sourceSha,BASELINE);
 assert.equal(input.inventory.definitions.length,input.inventory.counts.component_definitions);
 assert.equal(input.inventory.definitions.flatMap(x=>x.native_surfaces).length,input.inventory.counts.native_surface_candidates);
 let source=generateSourceMap(input);
 assert.equal(source.inventory_sha256,sha(input.inventoryBytes));assert.equal(source.supplemental_sha256,sha(input.supplementalBytes));
 assert.deepEqual(source.definitions.map(d=>d.id).sort(),input.inventory.definitions.map(d=>d.id).sort());
 assert.deepEqual(source.route_instances.map(d=>d.id).sort(),input.inventory.route_instances.map(d=>d.id).sort());
 assert.deepEqual(source.definitions.flatMap(d=>d.natives).map(n=>n.id).sort(),input.inventory.definitions.flatMap(d=>d.native_surfaces).map(n=>n.id).sort());
 const rail=source.definitions.find(d=>d.component==='ContextRail');assert.equal(rail.module_membership.client_importable,true);assert.deepEqual(rail.environment_candidates,['server']);assert.equal(rail.host_marker.eligible,false);
 const section=source.definitions.find(d=>d.component==='RailSection');assert.deepEqual(section.environment_candidates,['client']);
 for(const d of source.definitions)if(d.resolution.status==='resolved'){const s=d.resolution.span;assert.equal(s.sha256,sha(input.files[s.source].slice(s.start,s.end)));}
 const sourceHash=sha(json(source));source=null;
 assert.equal(sha(json(generateSourceMap(input))),sourceHash);
 const target=generateTargetMap(input);assert.equal(target.definitions.length,input.inventory.definitions.length);assert.equal(sha(json(target)),sha(json(generateTargetMap(input))));
 assert.ok(target.definitions.flatMap(d=>d.api_calls).some(x=>x.status==='resolved'));
 assert.ok(target.definitions.flatMap(d=>d.store_reads).some(x=>x.status==='resolved'));
});
