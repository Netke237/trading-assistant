'use strict';
const {ts,context,all,isFn,functionName,cli}=require('./map-common.cjs');
// Pure potential-input associations, partitioned by historical definition ID.
function generateTargetMap(input){
 const c=context(input),apiSource='frontend/lib/api.ts';
 const decl=n=>{const ds=c.symbol(n)?.declarations||[];return ds.length===1?ds[0]:null;};
 function origin(n){const d=decl(n);return d&&{node:d,source:c.rel(d.getSourceFile().fileName),name:d.name?.getText()};}
 function isApi(n){const o=origin(n);return o?.source===apiSource&&o.name==='api'&&ts.isVariableDeclaration(o.node);}
 function apiAlias(n,seen=new Set()){if(!n||seen.has(n))return false;seen.add(n);if(isApi(n))return true;const d=decl(n);return !!(d&&ts.isVariableDeclaration(d)&&d.initializer&&apiAlias(d.initializer,seen));}
 function literal(n,seen=new Set()){if(!n||seen.has(n))return null;seen.add(n);if(ts.isStringLiteral(n)||ts.isNoSubstitutionTemplateLiteral(n))return n.text;if(ts.isBinaryExpression(n)&&n.operatorToken.kind===ts.SyntaxKind.PlusToken){const a=literal(n.left,new Set(seen)),b=literal(n.right,new Set(seen));return a!==null&&b!==null?a+b:null;}if(ts.isIdentifier(n)){const d=decl(n);if(d&&ts.isVariableDeclaration(d)&&(d.parent.flags&ts.NodeFlags.Const))return literal(d.initializer,seen);}return null;}
 function imported(n,name,module){let s=c.checker.getSymbolAtLocation(n);const ds=s?.declarations||[];return ds.some(d=>{if(!ts.isImportSpecifier(d))return false;const im=d.parent.parent.parent;return !d.isTypeOnly&&!im.importClause?.isTypeOnly&&im.moduleSpecifier?.text===module&&(d.propertyName?.text||d.name.text)===name;});}
 function pattern(n){
  if(!n)return null;const str=literal(n);if(str!==null)return {pattern:str,expressions:[]};
  if(ts.isTemplateExpression(n))return {pattern:n.head.text+n.templateSpans.map(s=>'${'+s.expression.getText()+'}'+s.literal.text).join(''),expressions:n.templateSpans.map(s=>({expression:s.expression.getText(),span:c.span(s.expression)}))};
  if(ts.isBinaryExpression(n)&&n.operatorToken.kind===ts.SyntaxKind.PlusToken){const a=pattern(n.left),b=pattern(n.right);if(a&&b)return {pattern:a.pattern+b.pattern,expressions:[...a.expressions,...b.expressions]};if(a)return {pattern:a.pattern+'${'+n.right.getText()+'}',expressions:[...a.expressions,{expression:n.right.getText(),span:c.span(n.right)}]};}
  return null;
 }
 function fetchMethod(call){
  const opts=call.arguments[1];if(!opts)return 'GET';if(!ts.isObjectLiteralExpression(opts))return null;
  // A spread could override a literal method; computed keys could do the same.
  if(opts.properties.some(p=>ts.isSpreadAssignment(p)||p.name&&ts.isComputedPropertyName(p.name)))return null;
  const methods=opts.properties.filter(p=>p.name?.getText().replace(/['"]/g,'')==='method');if(methods.length===0)return 'GET';if(methods.length!==1)return null;const m=literal(methods[0].initializer);return m&&/^(GET|HEAD|POST|PUT|PATCH|DELETE|OPTIONS)$/.test(m)?m:null;
 }
 function isGlobalFetch(n){return ts.isIdentifier(n)&&n.text==='fetch'&&!decl(n);}
 function stripBase(p,n){
  if(!p)return null;if(p.pattern.startsWith('/'))return p;
  // BASE_URL is a declared module-level base; retaining its expression separately avoids claiming a live origin.
  if(p.pattern.startsWith('${BASE_URL}/')){const sf=n.getSourceFile(),base=sf.statements.flatMap(s=>ts.isVariableStatement(s)?s.declarationList.declarations:[]).find(d=>d.name.getText()==='BASE_URL');if(base)return {pattern:p.pattern.slice('${BASE_URL}'.length),expressions:p.expressions.filter(e=>e.expression!=='BASE_URL'),base_expression:base.initializer?.getText()};}
  return null;
 }
 function endpoint(call){
  if(isGlobalFetch(call.expression)){const method=fetchMethod(call),p=stripBase(pattern(call.arguments[0]),call);return method&&p?{status:'resolved',method,path_pattern:p.pattern,path_expressions:p.expressions,span:c.span(call),base_expression:p.base_expression||null}:{status:'unsupported',reason:'dynamic-http-method-or-path',span:c.span(call)};}
  const helper=decl(call.expression);if(!helper||!ts.isFunctionDeclaration(helper)||c.rel(helper.getSourceFile().fileName)!==apiSource)return null;
  const fetches=all(helper,n=>ts.isCallExpression(n)&&isGlobalFetch(n.expression));if(fetches.length!==1)return {status:'unsupported',reason:'unresolved-http-helper',span:c.span(call)};
  const f=fetches[0],pathParam=helper.parameters[0]?.name;
  // The wrapper must actually send its first parameter as URL suffix, once.
  const url=f.arguments[0];const hits=pathParam?all(url,n=>ts.isIdentifier(n)&&c.symbol(n)===c.symbol(pathParam)):[];
  const urlShape=url&&(ts.isTemplateExpression(url)&&url.templateSpans.length===2&&url.head.text===''&&url.templateSpans[0].expression.getText()==='BASE_URL'&&url.templateSpans[0].literal.text===''&&url.templateSpans[1].expression.getText()===pathParam?.getText()&&url.templateSpans[1].literal.text===''||ts.isBinaryExpression(url)&&url.operatorToken.kind===ts.SyntaxKind.PlusToken&&url.left.getText()==='BASE_URL'&&url.right.getText()===pathParam?.getText());
  const method=fetchMethod(f),p=pattern(call.arguments[0]);return hits.length===1&&urlShape&&method&&p?.pattern.startsWith('/')?{status:'resolved',method,path_pattern:p.pattern,path_expressions:p.expressions,span:c.span(call),helper_span:c.span(helper),fetch_span:c.span(f)}:{status:'unsupported',reason:'unresolved-http-helper-or-dynamic-path',span:c.span(call)};
 }
 const apiDecls=c.sources.get(apiSource)?all(c.sources.get(apiSource),n=>ts.isVariableDeclaration(n)&&n.name.getText()==='api'):[];
 const apiShapeUnresolved=apiDecls.length!==1||!ts.isObjectLiteralExpression(apiDecls[0].initializer)||apiDecls[0].initializer.properties.some(p=>ts.isSpreadAssignment(p)||p.name&&ts.isComputedPropertyName(p.name));
 const apiMembers=new Map();if(apiDecls.length===1&&ts.isObjectLiteralExpression(apiDecls[0].initializer)){for(const p of apiDecls[0].initializer.properties){if(!ts.isPropertyAssignment(p)&&!ts.isMethodDeclaration(p))continue;const name=p.name.getText().replace(/['"]/g,'');const fn=ts.isMethodDeclaration(p)?p:p.initializer;if(!isFn(fn))continue;const endpoints=all(fn,n=>ts.isCallExpression(n)).map(endpoint).filter(Boolean);if(!apiMembers.has(name))apiMembers.set(name,[]);apiMembers.get(name).push({span:c.span(p),endpoints});}}
 function resolveStore(n){
  const o=origin(n);if(!o||!ts.isVariableDeclaration(o.node)||!o.node.initializer)return null;
  // Binding identity, not spelling, establishes Zustand create/persist.
  const creates=all(o.node.initializer,x=>ts.isCallExpression(x)&&imported(x.expression,'create','zustand'));
  if(creates.length===0)return null;
  let factory=o.node.initializer;while(ts.isParenthesizedExpression(factory)||ts.isAsExpression(factory))factory=factory.expression;
  let stateCreator=null;
  if(ts.isCallExpression(factory)&&imported(factory.expression,'create','zustand')&&factory.arguments.length===1)stateCreator=factory.arguments[0];
  else if(ts.isCallExpression(factory)&&ts.isCallExpression(factory.expression)&&imported(factory.expression.expression,'create','zustand')&&factory.expression.arguments.length===0&&factory.arguments.length===1)stateCreator=factory.arguments[0];
  if(!stateCreator)return {status:'unsupported',reason:'unresolved-store-factory',store_source:o.source,store_span:c.span(o.node)};
  if(!ts.isCallExpression(stateCreator)||!imported(stateCreator.expression,'persist','zustand/middleware'))return {status:'unsupported',reason:'non-persisted-or-unsupported-store-wrapper',store_source:o.source,store_span:c.span(o.node)};
  const persists=[stateCreator];
  const options=persists[0].arguments[1];if(!options||!ts.isObjectLiteralExpression(options))return {status:'unsupported',reason:'dynamic-storage-options',store_source:o.source,store_span:c.span(o.node)};
  const names=options.properties.filter(p=>p.name?.getText().replace(/['"]/g,'')==='name');
  const uncertain=options.properties.some(p=>ts.isSpreadAssignment(p)||p.name&&ts.isComputedPropertyName(p.name));
  const name=names.length===1&&!uncertain?literal(names[0].initializer):null;
  return name!==null?{status:'resolved',storage_name:name,store_source:o.source,store_span:c.span(o.node),name_span:c.span(names[0])}:{status:'unsupported',reason:'dynamic-storage-name',store_source:o.source,store_span:c.span(o.node)};
 }
 function nestedNamed(call,root){for(let p=call.parent;p&&p!==root;p=p.parent)if(isFn(p)&&functionName(p))return p;return null;}
 const definitions=[...(input.inventory.definitions||[])].sort((a,b)=>a.id.localeCompare(b.id)).map(d=>{
  const r=c.resolveDefinition(d),api_calls=[],store_reads=[],unsupported=[];if(r.node){
   for(const call of all(r.node,ts.isCallExpression)){
    const span=c.span(call),expression=call.expression,arguments_=call.arguments.map(a=>a.getText());
    if(nestedNamed(call,r.node)){unsupported.push({reason:'unrelated-nested-definition',span,expression:expression.getText()});continue;}
    const member=ts.isPropertyAccessExpression(expression)?expression.name.text:null;
    const receiver=ts.isPropertyAccessExpression(expression)||ts.isElementAccessExpression(expression)?expression.expression:null;
    if(receiver&&isApi(receiver)){
     if(!member){api_calls.push({status:'unsupported',reason:'computed-api-member',span,arguments:arguments_});continue;}
     const rows=apiMembers.get(member)||[];if(apiShapeUnresolved||rows.length!==1){api_calls.push({status:'unsupported',reason:'missing-or-ambiguous-api-member',member,span,arguments:arguments_});continue;}
     const endpoints=rows[0].endpoints;api_calls.push({status:endpoints.length&&endpoints.every(e=>e.status==='resolved')?'resolved':'unsupported',reason:endpoints.length&&endpoints.every(e=>e.status==='resolved')?null:'unresolved-api-endpoint',member,span,api_member_span:rows[0].span,endpoints,arguments:arguments_});continue;
    }
    if(receiver&&apiAlias(receiver)){unsupported.push({reason:'api-alias',span,expression:expression.getText()});continue;}
    const storeReceiver=member==='getState'?receiver:ts.isIdentifier(expression)?expression:null;
    const store=storeReceiver&&resolveStore(storeReceiver);if(store){store_reads.push({...store,kind:member==='getState'?'getState':'hook',span,arguments:arguments_});continue;}
    const base=receiver||expression;const binding=decl(base);
    const parentSupplied=binding&&(ts.isParameter(binding)||ts.isBindingElement(binding)&&all(r.node,n=>ts.isParameter(n)).some(p=>p.pos<=binding.pos&&p.end>=binding.end));
    const looksTarget=/api|store/i.test(base.getText());
    unsupported.push({reason:parentSupplied?'parent-supplied-call':looksTarget?'shadowed-or-unresolved-target-binding':'unclassified-call-not-a-direct-api-or-store-target',span,expression:expression.getText()});
   }
   // Taking a member/alias without calling it is also unsupported target flow.
   for(const n of all(r.node,ts.isVariableDeclaration)){if(n.initializer&&apiAlias(n.initializer)&&!isApi(n.name))unsupported.push({reason:'api-alias',span:c.span(n),expression:n.getText()});}
  }
  const {node,...resolution}=r;return {id:d.id,source:d.source,component:d.component,resolution,api_calls,store_reads,unsupported,association:'potential-input-only; request or seed is not a state predicate'};
 });
 return {schema_version:1,purpose:'tooling-self-test',map_kind:'target-candidates',...c.provenance,definitions,unsupported_contract:['transitive imports are not direct calls','parent props and unresolved aliases are unsupported','all state predicates require independent runtime evidence']};
}
module.exports={generateTargetMap};if(require.main===module)cli(generateTargetMap);
