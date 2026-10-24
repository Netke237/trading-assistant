'use strict';
const {test}=require('node:test');const assert=require('node:assert/strict');
const {generateSourceMap}=require('../source-map.cjs');
const {generateTargetMap}=require('../target-map.cjs');
const fixture=require('../../fixtures/source/case.cjs');
const get=(map,name)=>map.definitions.find(d=>d.component===name);
test('comments/directives, aliases, barrels and type-only edges remain source-backed',()=>{
 const m=generateSourceMap(fixture);
 assert.equal(m.modules.find(x=>x.source==='frontend/client.tsx').explicit_client,true);
 assert.ok(m.modules.find(x=>x.source==='frontend/rail.tsx').client_member);
 assert.ok(m.modules.find(x=>x.source==='frontend/barrel.ts').edges.some(x=>x.specifier==='./ghost'&&x.kind==='type-only'));
 assert.equal(m.modules.find(x=>x.source==='frontend/app/page.tsx').client_member,false);
 assert.ok(m.modules.find(x=>x.source==='frontend/lib/store.ts').edges.some(x=>x.status==='unresolved-runtime'));
});
test('mixed server/client invocations are per callsite; module client membership never decides invocation',()=>{
 const m=generateSourceMap(fixture),r=get(m,'Rail');
 assert.deepEqual(r.environment_candidates,['client','server']);
 const calls=m.definitions.flatMap(x=>x.callsites).filter(x=>x.tag==='Rail');
 assert.deepEqual(calls.map(x=>x.environment_candidates).sort(),[['client'],['server']]);
 assert.equal(r.host_marker.eligible,false);
});
test('lexical ownership, children slots and duplicate signatures cannot earn unique native credit',()=>{
 const m=generateSourceMap(fixture),c=get(m,'Client');
 assert.equal(c.natives.length,2);
 for(const n of c.natives){assert.equal(n.resolution.status,'unresolved-source');assert.equal(n.resolution.reason,'ambiguous-native-signature');}
 const current=c.authored_jsx.filter(x=>x.tag==='button');
 assert.equal(current.length,2);assert.ok(current.every(x=>x.authorship==='children-slot'));
 assert.ok(current.every(x=>x.custom_ancestors[0].tag==='SectionCard'));
 assert.ok(m.signature_collisions.some(x=>x.members.length===2));
});
test('direct API/store association is per resolved definition; unsupported cases are explicit',()=>{
 const m=generateTargetMap(fixture),c=get(m,'Client'),o=get(m,'Other'),s=get(m,'Shadow');
 assert.deepEqual(c.api_calls.filter(x=>x.status==='resolved').map(x=>x.member).sort(),['item','list']);
 assert.deepEqual(o.api_calls.filter(x=>x.status==='resolved').map(x=>x.member),['other']);
 assert.equal(s.api_calls.filter(x=>x.status==='resolved').length,0);
 assert.ok(c.api_calls.some(x=>x.reason==='computed-api-member'));
 assert.ok(c.unsupported.some(x=>x.reason==='api-alias'));
 assert.ok(c.unsupported.some(x=>x.reason==='unrelated-nested-definition'));
 assert.ok(c.unsupported.some(x=>x.reason==='parent-supplied-call'));
 assert.deepEqual(c.store_reads.filter(x=>x.status==='resolved').map(x=>x.storage_name),['fixture-store','fixture-store']);
 assert.ok(c.store_reads.some(x=>x.reason==='dynamic-storage-name'));
 const item=c.api_calls.find(x=>x.member==='item');assert.equal(item.endpoints[0].method,'POST');assert.equal(item.endpoints[0].path_pattern,'/item/${id}');assert.deepEqual(item.arguments,["'A'"]);
});
test('generation is byte deterministic and preserves every inventory id including unresolved ones',()=>{
 const extra={...fixture,inventory:{...fixture.inventory,definitions:[...fixture.inventory.definitions,{id:'missing',source:'frontend/client.tsx',component:'Missing',native_surfaces:[{id:'lost-native',tag:'button'}]}]}};
 for(const gen of [generateSourceMap,generateTargetMap]){const a=gen(extra),b=gen(extra);assert.equal(JSON.stringify(a),JSON.stringify(b));assert.equal(a.definitions.length,extra.inventory.definitions.length);assert.equal(a.definitions.find(x=>x.id==='missing').resolution.status,'unresolved-source');}
});

test('missing/changed natives, duplicate declarations and new route entries are explicit without invented inventory ids',()=>{
 const input={...fixture,files:{...fixture.files,'frontend/app/new/page.tsx':'export default function New(){return <div/>}','frontend/rail.tsx':fixture.files['frontend/rail.tsx']+'\nfunction Rail(){return <footer/>}'},inventory:{...fixture.inventory,definitions:fixture.inventory.definitions.map(d=>d.component==='Client'?{...d,native_surfaces:[...d.native_surfaces,{id:'changed-native',tag:'a',attributes:[],text:'gone'}]}:d)}};
 const m=generateSourceMap(input);assert.equal(get(m,'Rail').resolution.reason,'ambiguous-declaration');assert.equal(get(m,'Client').natives.find(x=>x.id==='changed-native').resolution.reason,'missing-or-changed-native-signature');assert.deepEqual(m.new_route_entries.map(x=>x.source),['frontend/app/new/page.tsx']);assert.equal(m.definitions.some(x=>x.component==='New'),false);
});

test('dynamic API paths and methods, computed object members, store factories and shadowed helpers stay unsupported',()=>{
 const changed={...fixture,files:{...fixture.files,
 'frontend/client.tsx':fixture.files['frontend/client.tsx'].replace("api.list(); api.item('A');", "api.list(); api.item('A'); api.dynamic('unsafe'); useFake();").replace("import {useStore, useDynamic}","import {useStore, useDynamic, useFake}"),
 'frontend/lib/store.ts':fixture.files['frontend/lib/store.ts']+"\nexport const useFake=(()=>{const unused=create()(persist(()=>({}),{name:'wrong'}));return ()=>({})})();",
 'frontend/lib/api.ts':fixture.files['frontend/lib/api.ts'].replace("other:()=>get('/other')","other:()=>get('/other')")
 }};
 const m=generateTargetMap(changed),c=get(m,'Client');assert.ok(c.api_calls.some(x=>x.member==='dynamic'&&x.status==='unsupported'));assert.ok(c.store_reads.some(x=>x.reason==='unresolved-store-factory'));assert.ok(get(m,'Shadow').unsupported.some(x=>x.reason==='shadowed-or-unresolved-target-binding'));
 const computed={...fixture,files:{...fixture.files,'frontend/lib/api.ts':fixture.files['frontend/lib/api.ts'].replace("export const api={","export const api={['list']:()=>get('/override'),")}};
 assert.equal(get(generateTargetMap(computed),'Client').api_calls.filter(x=>x.status==='resolved').length,0);
 const dynamicMethod={...fixture,files:{...fixture.files,'frontend/lib/api.ts':fixture.files['frontend/lib/api.ts'].replace("method:'POST'","method:globalThis.method")}};
 assert.equal(get(generateTargetMap(dynamicMethod),'Client').api_calls.find(x=>x.member==='item').status,'unsupported');
});

test('a route file alone cannot resolve its missing or ambiguous entry declaration',()=>{
 const missing={...fixture,files:{...fixture.files,'frontend/app/page.tsx':'export const metadata = {};'}};
 assert.equal(generateSourceMap(missing).route_entries[0].resolution.status,'unresolved-source');
 const duplicate={...fixture,files:{...fixture.files,'frontend/app/page.tsx':'export default function A(){return <div/>}; export default function B(){return <div/>}'}};
 assert.equal(generateSourceMap(duplicate).route_entries[0].resolution.status,'unresolved-source');
});

test('duplicate historical signatures never become unique when only one current authored node survives',()=>{
 const input={...fixture,files:{...fixture.files,'frontend/client.tsx':fixture.files['frontend/client.tsx'].replace('<button title="same">Same</button><button title="same">Same</button>','<button title="same">Same</button>')}};
 const m=generateSourceMap(input);assert.ok(get(m,'Client').natives.every(n=>n.resolution.status==='unresolved-source'));assert.ok(m.inventory_signature_collisions.some(x=>x.native_ids.includes('native:one')&&x.native_ids.includes('native:two')));
});

test('historical route joins do not establish current reachability after imports disappear',()=>{
 const changed={...fixture,files:{...fixture.files,'frontend/app/page.tsx':'export default function Page(){return <main/>}'}};
 const row=generateSourceMap(changed).route_instances.find(i=>i.definition_id.endsWith('#Client'));
 assert.equal(row.resolution.status,'unresolved-source');assert.equal(row.resolution.reason,'historical-instance-module-not-currently-reachable');
});
