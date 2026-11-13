'use strict';
const {ts,context,all,isFn,functionName,sha,json,compact,cli}=require('./map-common.cjs');
const open=n=>ts.isJsxElement(n)?n.openingElement:ts.isJsxSelfClosingElement(n)?n:null;
const historical=s=>s.length>240?s.slice(0,237)+'...':s;
const historicalText=n=>historical(n.getText().replace(/\s+/g,' ').trim());
function conditions(n){const out=[];for(let p=n.parent;p;p=p.parent){if(ts.isIfStatement(p))out.push(historicalText(p.expression));if(ts.isConditionalExpression(p))out.push(historicalText(p.condition));if(ts.isBinaryExpression(p)&&[ts.SyntaxKind.AmpersandAmpersandToken,ts.SyntaxKind.BarBarToken,ts.SyntaxKind.QuestionQuestionToken].includes(p.operatorToken.kind))out.push(historicalText(p.left));if(ts.isCallExpression(p)&&/\.map$/.test(p.expression.getText()))out.push('repeated: '+historicalText(p.expression));}return out;}
function lexicalOwner(n){for(let p=n.parent;p;p=p.parent)if(isFn(p)&&functionName(p))return p;return null;}
// Pure candidate generator. No host marker or runtime verification is inferred here.
function generateSourceMap(input){
 const c=context(input),defs=[...(input.inventory.definitions||[])].sort((a,b)=>a.id.localeCompare(b.id));
 const client=new Set(c.closure(c.modules.filter(x=>x.explicit_client).map(x=>x.source)));
 for(const m of c.modules){m.client_member=client.has(m.source);m.client_membership_evidence={directive_seed:m.explicit_client,incoming_edges:c.modules.filter(x=>client.has(x.source)).flatMap(x=>x.edges.filter(e=>e.status==='resolved-runtime'&&e.target===m.source).map(e=>({source:x.source,span:e.span})))};}
 const resolved=new Map(defs.map(d=>[d.id,c.resolveDefinition(d)]));
 function target(tag){if(isFn(tag))return tag;const s=c.symbol(tag);if(!s)return null;for(const d of s.declarations||[]){if(isFn(d))return d;if(ts.isVariableDeclaration(d)){const fs=all(d.initializer||d,isFn).filter(f=>functionName(f)===s.name);if(fs.length===1)return fs[0];}}return null;}
 const allJsx=[];for(const [source,sf] of c.sources)for(const node of all(sf,n=>!!open(n))){
  const o=open(node),tag=o.tagName.getText(sf),attributes=o.attributes.properties.map(a=>ts.isJsxAttribute(a)?{name:a.name.getText(sf),value:a.initializer?historicalText(a.initializer):true,dynamic:!!a.initializer&&!ts.isStringLiteral(a.initializer),span:c.span(a)}:{name:'...spread',value:historicalText(a),dynamic:true,span:c.span(a)});
  const ancestors=[];for(let p=node.parent;p;p=p.parent){const op=open(p);if(op&&!/^[a-z]/.test(op.tagName.getText(sf)))ancestors.unshift({tag:op.tagName.getText(sf),span:c.span(p)});}
  const childrenSlot=ancestors.length>0;
  const literalText=ts.isJsxElement(node)?node.children.filter(ts.isJsxText).map(x=>x.text.replace(/\s+/g,' ').trim()).filter(Boolean).join(' '):'';
  const rawText=historical(node.getText(sf).replace(/\s+/g,' ').trim().replace(/<[^>]+>/g,' ').replace(/\s+/g,' '));
  const historicalSignature={tag,attributes:attributes.filter(a=>!['className','style','...spread'].includes(a.name)).map(a=>({name:a.name,value:a.value})),text:rawText.trim(),conditions:conditions(node)};
  // DOM selectors cannot use handler expressions, styles or unresolved attributes as identity.
  const literals=attributes.filter(a=>!a.dynamic&&!/^on[A-Z]/.test(a.name)).map(a=>({name:a.name,value:a.value}));
  const signature={tag,attributes:literals,text:literalText};
  const row={id:`jsx:${source}:${node.getStart(sf)}`,tag,kind:/^[a-z]/.test(tag)?'native':'custom',span:c.span(node),attributes,literal_text:literalText,signature,signature_hash:sha(json(signature)),historical_signature:historicalSignature,dynamic_attributes:attributes.filter(a=>a.dynamic).map(a=>a.name),conditional_expressions:conditions(node),custom_ancestors:ancestors,authorship:childrenSlot?'children-slot':'lexical-definition',owner:lexicalOwner(node),target:target(o.tagName),node};
  allJsx.push(row);
 }
 const owned=new Map();for(const x of allJsx){if(!owned.has(x.owner))owned.set(x.owner,[]);owned.get(x.owner).push(x);}
 const routes=[...(input.inventory.route_entries||[])].sort((a,b)=>a.id.localeCompare(b.id)).map(e=>{
  const roots=[...new Set([e.source,...(e.attached_entry_sources||[])])].sort();const reachable=c.closure(roots),traversal=c.closure(roots,true),server=traversal.filter(f=>!c.moduleByFile.get(f)?.explicit_client),boundaries=traversal.filter(f=>c.moduleByFile.get(f)?.explicit_client);
  const environments=new Map(),reasons=new Map(),queue=[];
  function add(n,env,reason){if(!n)return;let set=environments.get(n);if(!set){set=new Set();environments.set(n,set);reasons.set(n,[]);}if(!set.has(env)){set.add(env);queue.push([n,env]);}reasons.get(n).push(reason);}
  function entryCandidates(f){const sf=c.sources.get(f);if(!sf)return [];const result=[];
   for(const n of sf.statements){if(ts.isFunctionDeclaration(n)&&n.modifiers?.some(m=>m.kind===ts.SyntaxKind.DefaultKeyword))result.push(n);
    if(ts.isExportAssignment(n))result.push(target(n.expression));
    if(ts.isExportDeclaration(n)&&n.exportClause&&ts.isNamedExports(n.exportClause))for(const ex of n.exportClause.elements)if(ex.name.text==='default')result.push(target(ex.propertyName||ex.name));
   }return result;
  }
  const entry=entryCandidates(e.source);
  for(const f of roots){const candidates=entryCandidates(f);if(candidates.length!==1||!candidates[0])continue;const n=candidates[0];add(n,c.moduleByFile.get(f)?.explicit_client||c.moduleByFile.get(c.rel(n.getSourceFile().fileName))?.explicit_client?'client':'server',{kind:'route-root',source:f,span:c.span(n)});}
  while(queue.length){const [n,env]=queue.shift();for(const call of owned.get(n)||[]){if(call.kind!=='custom'||!call.target)continue;const f=c.rel(call.target.getSourceFile().fileName);add(call.target,c.moduleByFile.get(f)?.explicit_client?'client':env,{kind:'jsx-invocation',caller:c.span(n),callsite:call.span,inherited_environment:env});}}
  return {id:e.id,source:e.source,resolution:entry.length===1&&entry[0]?{status:'resolved',span:c.span(entry[0]),module_sha256:sha(c.files[e.source]),inventory_hash_matches:e.source_sha256?e.source_sha256===sha(c.files[e.source]):null}:{status:'unresolved-source',reason:entry.length>1?'ambiguous-route-entry-declaration':'missing-or-unsupported-route-entry-declaration'},roots,runtime_reachable_modules:reachable,server_traversal:server,server_client_boundaries:boundaries,environments,reasons};
 });
 function environmentsFor(node,route){const rs=route?[route]:routes;const env=[...new Set(rs.flatMap(r=>[...(r.environments.get(node)||[])]))].sort();return env.length?env:['mixed-or-unresolved'];}
 function cleanJsx(x){const {owner,target,node,...row}=x;return {...row,environment_candidates:environmentsFor(owner),environment_reason_reference:owner?c.span(owner):null,resolved_callee:target?c.span(target):null,binding_status:row.kind==='custom'?(target?'resolved':'unresolved-runtime-binding'):'native-tag',unresolved_data_flow:'arbitrary props and children are not reconstructed'};}
 const historicalKey=n=>({tag:n.tag,attributes:(n.attributes||[]).map(a=>({name:a.name,value:a.value})),text:(n.text||'').trim(),conditions:n.conditions||[]});
 const definitions=defs.map(d=>{
  const r=resolved.get(d.id),node=r.node,own=node?owned.get(node)||[]:[];
  const natives=[...(d.native_surfaces||[])].sort((a,b)=>a.id.localeCompare(b.id)).map(n=>{
   const key=historicalKey(n),inventoryDuplicates=(d.native_surfaces||[]).filter(other=>json(historicalKey(other))===json(key)).length>1;
   const found=own.filter(x=>json(x.historical_signature)===json(key));
   const resolution=r.status!=='resolved'?{status:'unresolved-source',reason:'unresolved-parent-definition'}:found.length===1&&!inventoryDuplicates?{status:'resolved',span:found[0].span}:{status:'unresolved-source',reason:found.length||inventoryDuplicates?'ambiguous-native-signature':'missing-or-changed-native-signature'};
   return {id:n.id,parent_definition_id:d.id,inventory_signature:key,kind:/^[a-z]/.test(n.tag)?'native':'custom-component-candidate',resolution,candidate_spans:found.map(x=>x.span),authored_jsx_id:found.length===1?found[0].id:null,signature_hash:found.length===1?found[0].signature_hash:null,authorship:found.length===1?found[0].authorship:'unresolved',custom_ancestors:found.length===1?found[0].custom_ancestors:[],signature:found.length===1?found[0].signature:null,host_marker:{eligible:false,reason:'requires-reviewed-route-unique-visible-connected-runtime-adapter'}};
  });
  const {node:_,...resolution}=r;
  return {id:d.id,source:d.source,component:d.component,resolution,module_membership:{client_importable:client.has(d.source),explicit_client:c.moduleByFile.get(d.source)?.explicit_client||false,server_route_entries:routes.filter(r=>r.server_traversal.includes(d.source)).map(r=>r.id)},environment_candidates:node?environmentsFor(node):['mixed-or-unresolved'],environment_evidence:node?routes.flatMap(r=>(r.reasons.get(node)||[]).map(reason=>({route_entry_id:r.id,...reason}))):[],callsites:own.filter(x=>x.kind==='custom').map(cleanJsx),authored_jsx:own.filter(x=>x.kind==='native').map(cleanJsx),natives,host_marker:{eligible:false,reason:'no-reviewed-runtime-marker-adapter; generic hosts and lexical ownership do not prove identity'}};
 });
 const signature_collisions=[];for(const r of routes){const groups=new Map();for(const x of allJsx){if(x.kind!=='native'||!r.runtime_reachable_modules.includes(x.span.source))continue;const k=x.signature_hash;if(!groups.has(k))groups.set(k,[]);groups.get(k).push(x);}for(const [signature_hash,rows] of groups)if(rows.length>1)signature_collisions.push({route_entry_id:r.id,signature_hash,members:rows.map(x=>({jsx_id:x.id,span:x.span})),disposition:'observed-ambiguous',reason:'never-disambiguate-by-dom-order-or-count'});}
 const inventory_signature_collisions=[];for(const r of routes){const relevant=new Set((input.inventory.route_instances||[]).filter(i=>i.route_entry_id===r.id).map(i=>i.definition_id));const groups=new Map();for(const d of defs.filter(d=>relevant.has(d.id)))for(const n of d.native_surfaces||[]){const key=json(historicalKey(n));if(!groups.has(key))groups.set(key,[]);groups.get(key).push(n.id);}for(const [key,native_ids] of groups)if(native_ids.length>1)inventory_signature_collisions.push({route_entry_id:r.id,signature_hash:sha(key),native_ids,disposition:'observed-ambiguous'});}
 const inventoryRoutes=new Set((input.inventory.route_entries||[]).map(e=>e.source));
 const new_route_entries=[...c.sources.keys()].filter(f=>/^frontend\/app\//.test(f)&&/\/(page|layout|default|loading|error|not-found|global-error)\.tsx?$/.test(f)&&!inventoryRoutes.has(f)).map(source=>({source,span:c.span(c.sources.get(source)),reason:'current-route-entry-absent-from-historical-inventory'}));
 const route_instances=[...(input.inventory.route_instances||[])].sort((a,b)=>a.id.localeCompare(b.id)).map(i=>{const r=routes.find(r=>r.id===i.route_entry_id),d=resolved.get(i.definition_id),reachable=r&&d?.node&&r.runtime_reachable_modules.includes(c.rel(d.node.getSourceFile().fileName));return {id:i.id,route_entry_id:i.route_entry_id,definition_id:i.definition_id,resolution:r?.resolution.status==='resolved'&&d?.status==='resolved'&&reachable?{status:'candidate',environment_candidates:environmentsFor(d.node,r),reason:'potential-source-reachability-is-not-runtime-observation'}:{status:'unresolved-source',reason:!r?'missing-route-entry':r.resolution.status!=='resolved'?'unresolved-route-entry':d?.status!=='resolved'?'unresolved-definition':'historical-instance-module-not-currently-reachable'}};});
 return {schema_version:1,purpose:'tooling-self-test',map_kind:'source-candidates',...c.provenance,modules:c.modules,route_entries:routes.map(({environments,reasons,...r})=>r),definitions,route_instances,signature_collisions,inventory_signature_collisions,new_route_entries,unsupported:[{reason:'arbitrary-prop-and-children-flow',verified_credit:false},{reason:'no-source-only-runtime-identity-or-host-marker-credit',verified_credit:false}]};
}
module.exports={generateSourceMap};if(require.main===module)cli(generateSourceMap);
