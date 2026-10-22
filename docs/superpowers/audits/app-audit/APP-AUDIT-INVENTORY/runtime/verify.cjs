const assert=require('assert/strict'),fs=require('fs'),path=require('path'),crypto=require('crypto');
const dir=__dirname,inventory=require('../inventory.json');
const sha=data=>crypto.createHash('sha256').update(data).digest('hex');
const dirs=fs.readdirSync(dir,{withFileTypes:true}).filter(d=>d.isDirectory()&&fs.existsSync(path.join(dir,d.name,'observations.json'))).map(d=>d.name);
let observed=0,networkCount=0,hashedPayloads=0;
for(const folder of dirs){
 const read=name=>JSON.parse(fs.readFileSync(path.join(dir,folder,name),'utf8'));
 const observations=read('observations.json'),network=read('network.json'),payloads=read('mock-payloads.json'),provenance=read('provenance.json');
 assert.equal(provenance.source_baseline,inventory.source_baseline);assert.equal(provenance.real_backend_requests_allowed,0);assert.equal(provenance.playwright,'1.62.1');assert.equal(provenance.next,'15.5.23');
 const ids=new Set();for(const row of observations){assert(!ids.has(row.id),'duplicate observation ID in '+folder+': '+row.id);ids.add(row.id);if(row.status!=='observed'){assert.equal(row.status,'unavailable');assert(row.error);continue;}observed++;assert(row.state?.text);assert(row.storage?.local&&row.storage?.session);for(const i of row.network_indices)assert(network[i],'dangling network index '+i);}
 for(const [hash,p]of Object.entries(payloads)){assert.equal(hash,sha(p.body));assert.equal(p.sha256,hash);hashedPayloads++;}
 for(const n of network){assert(['mocked','blocked-unmatched','blocked-fixture-continue','closed-before-connect'].includes(n.action),'unrecognized egress disposition');assert(n.path.startsWith('/'));assert(!('headers'in n));if(n.action==='mocked'){assert(payloads[n.response_sha256]);if(n.request_body_sha256)assert(payloads[n.request_body_sha256]);}networkCount++;}
}
const routes=JSON.parse(fs.readFileSync(path.join(dir,'route-reconciliation.json'),'utf8'));assert.equal(routes.length,inventory.route_entries.length);assert.equal(new Set(routes.map(r=>r.route_entry_id)).size,45);assert(routes.every(r=>r.disposition&&r.outstanding_check));
const links=JSON.parse(fs.readFileSync(path.join(dir,'observation-source-links.json'),'utf8'));const definitions=new Set(inventory.definitions.map(d=>d.id)),native=new Set(inventory.definitions.flatMap(d=>d.native_surfaces.map(n=>n.id))),states=new Set(inventory.route_instances.flatMap(i=>i.state_ids));
for(const l of links){assert(l.surface_ids.every(id=>definitions.has(id)));assert(l.native_ids.every(id=>native.has(id)));assert(l.source_state_requirement_ids.every(id=>states.has(id)));}
const all=dirs.flatMap(folder=>JSON.parse(fs.readFileSync(path.join(dir,folder,'observations.json'),'utf8'))).filter(r=>r.status==='observed');
for(const id of ['boundary:notfound','boundary:frame-error','boundary:frame-reset','boundary:frame-loading-visible','min-width:default:1279','min-width:default:1280','min-width:trade-card:1199','min-width:trade-card:1200','min-width:position-card:1199','min-width:position-card:1200','mode:button:options','mode:button:stocks','mode:button:prebreakout','setup:submode:prebreakout','setup:submode:pullback','setup:submode:fib','shell:reject-dialog','shell:reject-cancel','shell:reject-proceed','tuning:expanded-two-folds'])assert(all.some(r=>r.id===id),'missing required positive shared-scope evidence '+id);
const findings=JSON.parse(fs.readFileSync(path.join(dir,'findings.json'),'utf8'));assert.equal(findings.length,2);for(const f of findings){assert(f.proof.length>=2,'rail finding not repeated');assert(f.proof.every(p=>p.retained_origin_source_id&&p.hard_expected_entry_id));assert.equal(f.fixture_payload_sha256,sha('[]'));}
console.log(JSON.stringify({verified:true,artifact_runs:dirs.length,observed,network_records:networkCount,hashed_payloads:hashedPayloads,route_entries:routes.length,note:'Evidence structure/source links/hash integrity and required shared-scope assertions only; no domain correctness certification'}));
