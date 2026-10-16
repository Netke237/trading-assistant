/* Report tooling only. Run from any cwd: node <this file>; --check verifies frozen outputs. */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const cp = require('node:child_process');
const report = __dirname;
const root = path.resolve(report, '../../../../..');
const front = path.join(root, 'frontend');
const ts = require(require.resolve('typescript', {paths: [front]}));
const slash = p => p.split(path.sep).join('/');
const rel = p => slash(path.relative(root, p));
const read = p => fs.readFileSync(path.join(root, p), 'utf8');
const sha = x => crypto.createHash('sha256').update(x).digest('hex');
const baseline = '27fe5182a90ae1b40bee53bdf01484b92dab136c';
const config = JSON.parse(read(rel(path.join(report, 'source-annotations.json'))));
const walkFiles = dir => fs.readdirSync(dir, {withFileTypes: true}).flatMap(e => {
  if (['node_modules', '.next', '__tests__', '__mocks__'].includes(e.name)) return [];
  const p = path.join(dir, e.name);
  return e.isDirectory() ? walkFiles(p) : [p];
});
const files = walkFiles(front).filter(f => /\.(tsx?|jsx?)$/.test(f) && !/\.(test|spec)\.[jt]sx?$/.test(f));
const sources = new Map(files.map(f => [rel(f), ts.createSourceFile(rel(f), fs.readFileSync(f, 'utf8'), ts.ScriptTarget.Latest, true, f.endsWith('x') ? ts.ScriptKind.TSX : ts.ScriptKind.TS)]));
const line = (sf, n) => sf.getLineAndCharacterOfPosition(n.getStart(sf)).line + 1;
const text = (sf, n) => n.getText(sf).replace(/\s+/g, ' ').trim();
const compact = s => s.length > 240 ? s.slice(0, 237) + '...' : s;
const descendants = (n, pred) => { const a=[]; const visit=x=>{if(pred(x))a.push(x); ts.forEachChild(x,visit);}; visit(n); return a; };
const isJsx = n => ts.isJsxElement(n) || ts.isJsxSelfClosingElement(n) || ts.isJsxFragment(n);
const jsxOpen = n => ts.isJsxElement(n) ? n.openingElement : ts.isJsxSelfClosingElement(n) ? n : null;
const settings = ts.readConfigFile(path.join(front, 'tsconfig.json'), ts.sys.readFile).config;
const options = ts.convertCompilerOptionsFromJson(settings.compilerOptions, front).options;
function resolve(file, spec) {
  const found=ts.resolveModuleName(spec,path.join(root,file),options,ts.sys).resolvedModule;
  if(!found || found.isExternalLibraryImport) return null;
  const p=rel(found.resolvedFileName);
  return sources.has(p) ? p : null;
}
const graph = [];
const dynamics=[];
for (const [file,sf] of sources) {
  const edges=[];
  for(const n of descendants(sf,n=>ts.isImportDeclaration(n)||ts.isExportDeclaration(n)||ts.isCallExpression(n))) {
    let spec=null,kind=null,typeOnly=false;
    if(ts.isImportDeclaration(n)) { spec=n.moduleSpecifier;kind='import';typeOnly=!!n.importClause?.isTypeOnly; }
    else if(ts.isExportDeclaration(n)) {spec=n.moduleSpecifier;kind='re-export';typeOnly=!!n.isTypeOnly;}
    else if(n.expression.kind===ts.SyntaxKind.ImportKeyword || n.expression.getText(sf)==='require') {spec=n.arguments[0];kind='dynamic-import';}
    if(!spec || !kind || typeOnly)continue;
    if(ts.isStringLiteralLike(spec)) {
      const target=resolve(file,spec.text);
      if(target)edges.push({target,kind,line:line(sf,n)});
      else if(spec.text.startsWith('.')||spec.text.startsWith('@/')) {
        if(!/\.(css|json|svg|png|jpg)$/.test(spec.text)) dynamics.push({source:file,line:line(sf,n),expression:spec.text,reason:'Local import not resolved as tracked source module'});
      }
    } else dynamics.push({source:file,line:line(sf,n),expression:compact(text(sf,spec)),reason:'Computed module import requires manual/runtime resolution'});
  }
  graph.push({source:file,edges});
}
const graphMap=new Map(graph.map(g=>[g.source,g.edges]));
const closure=roots=>{const seen=new Set();const visit=f=>{if(seen.has(f))return;seen.add(f);for(const e of graphMap.get(f)||[])visit(e.target);};roots.forEach(visit);return [...seen].sort();};
const entryFiles=[...sources.keys()].filter(f=>/^frontend\/app\//.test(f)&&/\/(page|layout|default|loading|error|not-found)\.tsx$/.test(f)).sort();
function urlFor(f){return '/'+f.slice('frontend/app/'.length).split('/').slice(0,-1).filter(s=>!s.startsWith('(')&&!s.startsWith('@')).join('/');}
function owner(f,name=''){
  const section=config.settings_sections.find(s=>s.source===f&&s.component===name);if(section)return section.owner;
  if(f.endsWith('/settings/page.tsx')&&/Tuning|ProposalCard/.test(name))return 'D';
  if(f.endsWith('/settings/page.tsx')&&/Edgar|Sp500/.test(name))return 'H';
  const s=f+' '+name;
  if(/(?:StoreHydration|InitStores|Hydration|searchProfilesStore|persist|migration)/i.test(s))return 'I';
  if(/(?:step-4-prebreakout|PreBreakout|FibPullback|SelectedSetup|fibonacci)/i.test(s))return 'E';
  if(/(?:portfolio|broker|StockSendDialog|SendToBrokerDialog|Risk|AutoTradeArm|AutoTradeClose)/i.test(s))return 'F';
  if(/(?:watchlist|watch|alert|notification|scheduled)/i.test(s))return 'G';
  if(/(?:settings|Params|Profile|step-[123]-|regime|universe|ConfigHealth)/i.test(s))return 'B';
  if(/(?:step-4-stocks|step-6-backtest|step-7-position|stock|strategy|Backtest|Confidence|PositionCard)/i.test(s))return 'D';
  if(/(?:step-4-ranking|step-5-vol|step-6-contract|step-7-trade|option|contract|tradecard|basket|IV|premium)/i.test(s))return 'C';
  return 'H';
}
const owners=(f,n='')=>({numeric:owner(f,n),persistence:'I',presentation:'J',navigation:'A'});
const entries=entryFiles.map(file=>{
  const sf=sources.get(file),kind=path.basename(file,'.tsx'),route=urlFor(file);
  const navigation=descendants(sf,n=>ts.isCallExpression(n)&&(/^(redirect|notFound)$/.test(n.expression.getText(sf))||/^(router\.(push|replace)|window\.open)$/.test(n.expression.getText(sf)))).map(n=>({line:line(sf,n),call:compact(text(sf,n)),enclosing_conditions:ancestors(n,sf)}));
  const rail=file.includes('/@contextRail/');
  const privateSegment=file.slice(13).split('/').find(x=>x.startsWith('_'));
  const redirect=kind==='page'&&navigation.some(n=>n.call.startsWith('redirect('));
  const classification=privateSegment?'private-folder-source':rail?(kind==='default'?'parallel-slot-fallback':'parallel-slot-page'):redirect?'redirect':kind==='page'?'url-page':kind==='layout'?'layout':kind==='default'?'fallback':kind+'-boundary';
  return {id:'route:'+file,source:file,line:1,route,kind,classification,parallel_slot:rail?'contextRail':null,owners:owners(file),exposure:privateSegment?'Next private underscore segment; runtime must confirm excluded URL':file.includes('/dev/')?'NODE_ENV development; notFound outside development':'normal route or boundary',navigation,runtime_status:'pending',runtime_requirement:rail?'Compare soft navigation retained slot, hard-reload fallback and browser back/forward':'Task 2 deterministic fixture visit, navigation/restoration; no live backend',source_sha256:sha(read(file))};
});
function ancestors(n,sf){const a=[];for(let p=n.parent;p&&p!==sf;p=p.parent){if(ts.isIfStatement(p))a.push(compact(text(sf,p.expression)));if(ts.isConditionalExpression(p))a.push(compact(text(sf,p.condition)));if(ts.isBinaryExpression(p)&&[ts.SyntaxKind.AmpersandAmpersandToken,ts.SyntaxKind.BarBarToken,ts.SyntaxKind.QuestionQuestionToken].includes(p.operatorToken.kind))a.push(compact(text(sf,p.left)));if(ts.isCallExpression(p)&&/\.map$/.test(text(sf,p.expression)))a.push('repeated: '+compact(text(sf,p.expression)));}return a;}
const rootsFor=e=>{
  const roots=[e.source];let dir=path.posix.dirname(e.source);
  while(dir.startsWith('frontend/app')){const f=dir+'/layout.tsx';if(sources.has(f))roots.push(f);if(dir==='frontend/app')break;dir=path.posix.dirname(dir);}
  // Slot attachment is explicit and not an import. Include only selected rail page or
  // applicable defaults, not every rail in the application. Retained soft-navigation
  // slots are a separate Task 2 check; source cannot decide browser history.
  if(!e.parallel_slot&&e.source.startsWith('frontend/app/(frame)/')){
    const railBase='frontend/app/(frame)/@contextRail';
    const exact=railBase+(e.route==='/'?'':e.route)+'/page.tsx';
    if(sources.has(exact))roots.push(exact);
    else{let r=e.route;while(true){const f=railBase+(r==='/'?'':r)+'/default.tsx';if(sources.has(f)){roots.push(f);break;}if(r==='/')break;r=path.posix.dirname(r);}}
  }
  return [...new Set(roots)].sort();
};
for(const e of entries){e.attached_entry_sources=rootsFor(e);e.reachable_modules=closure(e.attached_entry_sources);}
const reachable=new Set(entries.flatMap(e=>e.reachable_modules));
const definitions=[];
const functionNames=n=>{
  if(n.name?.text)return n.name.text;
  let p=n.parent;while(p&&(ts.isCallExpression(p)||ts.isParenthesizedExpression(p)))p=p.parent;
  if(p&&ts.isVariableDeclaration(p)&&ts.isIdentifier(p.name))return p.name.text;
  return null;
};
const functionNode=n=>ts.isFunctionDeclaration(n)||ts.isFunctionExpression(n)||ts.isArrowFunction(n);
function ownNodes(n,pred){const a=[];function visit(x){if(x!==n&&functionNode(x)){// JSX within .map/event/render callbacks still belongs to outer surface unless named component.
    const name=functionNames(x);if(name&&/^[A-Z]/.test(name))return;
  }if(pred(x))a.push(x);ts.forEachChild(x,visit);}visit(n);return a;}
for(const file of [...reachable].sort()){
  const sf=sources.get(file);if(!sf||!file.endsWith('x'))continue;
  const funcs=descendants(sf,functionNode).filter(n=>functionNames(n)&&(ownNodes(n,isJsx).length||['StoreHydration','InitStores','KeyboardShortcuts'].includes(functionNames(n))));
  for(const fn of funcs){
    const name=functionNames(fn);if(!/^[A-Z]/.test(name))continue;
    const nodes=ownNodes(fn,n=>!!jsxOpen(n));
    const native=[];const calls=[];
    for(const node of nodes){const open=jsxOpen(node);const tag=open.tagName.getText(sf);const attrs=open.attributes.properties.filter(ts.isJsxAttribute).map(a=>({name:a.name.getText(sf),value:a.initializer?compact(text(sf,a.initializer)):true,line:line(sf,a)}));
      const attrsMap=Object.fromEntries(attrs.map(a=>[a.name,a.value]));
      if(/^[A-Z]/.test(tag)) calls.push({component:tag,line:line(sf,node),conditions:ancestors(node,sf),props:attrs.filter(a=>/^(on|open|show|active|mode|category|tab|symbol|title|label|disabled|loading|data|rows|selected|children)/.test(a.name))});
      const categories=[];
      if(tag==='table'||/table|grid/.test(String(attrsMap.role)))categories.push('table');
      if(tag==='canvas'||tag==='svg')categories.push('canvas-or-svg');
      if(tag==='details')categories.push('nested-disclosure');
      if(/dialog|alertdialog/.test(String(attrsMap.role)))categories.push('dialog');
      if(/tab(list|panel)?/.test(String(attrsMap.role)))categories.push('tabs');
      if(attrsMap.title||attrsMap['data-tooltip']||attrsMap['aria-describedby']||attrsMap.role==='"tooltip"')categories.push('tooltip-or-description');
      if(attrsMap['aria-expanded'])categories.push('controlled-disclosure');
      if(['button','a','input','select','textarea','summary','form'].includes(tag)||attrsMap.onClick)categories.push('entry-or-control');
      if(/(?:table|chart|drawer|modal|tooltip|tabPanel|accordion|disclosure|collapse)/i.test(String(attrsMap.className)))categories.push('class-named-surface-candidate');
      if(categories.length)native.push({tag,categories,line:line(sf,node),attributes:attrs.filter(a=>!['className','style'].includes(a.name)),text:compact(text(sf,node).replace(/<[^>]+>/g,' ').replace(/\s+/g,' ')),conditions:ancestors(node,sf)});
    }
    const hooks=ownNodes(fn,n=>ts.isCallExpression(n)&&/^(?:React\.)?use(?:State|Effect|Memo|Reducer|Ref|SyncExternalStore)$/.test(text(sf,n.expression))).map(n=>({line:line(sf,n),call:compact(text(sf,n))}));
    const branches=ownNodes(fn,n=>ts.isIfStatement(n)||ts.isConditionalExpression(n)||ts.isBinaryExpression(n)&&[ts.SyntaxKind.AmpersandAmpersandToken,ts.SyntaxKind.QuestionQuestionToken].includes(n.operatorToken.kind)).filter(n=>descendants(n,isJsx).length).map(n=>({line:line(sf,n),condition:compact(text(sf,ts.isIfStatement(n)?n.expression:ts.isConditionalExpression(n)?n.condition:n.left))}));
    const id='surface:'+file+'#'+name;
    for(const manual of config.additional_surfaces.filter(s=>s.source===file&&s.component===name))native.push({id:id+'::'+manual.identity,...manual,parent_definition_id:id,owners:owners(file,name),observation:'source-observed manual readback',entry_action:manual.entry_action,state_matrix_template:'conservative-nine-state-v1',runtime_status:'pending'});
    const seenNative=new Map();
    for(const n of native){
      if(n.id)continue;
      const identity=sha(JSON.stringify({tag:n.tag,attributes:n.attributes.map(a=>({name:a.name,value:a.value})),text:n.text,conditions:n.conditions})).slice(0,12);
      const occurrence=(seenNative.get(identity)||0)+1;seenNative.set(identity,occurrence);
      n.id=id+'::native:'+n.tag+':'+identity+(occurrence>1?':duplicate-'+occurrence:'');
      n.source=file;n.parent_definition_id=id;n.owners=owners(file,name);
      n.observation='source-observed candidate';
      n.entry_action=n.attributes.filter(a=>/^on|^href$/.test(a.name)).map(a=>a.name+'='+a.value).join('; ')||'Reveal parent component and satisfy enclosing conditions; tooltip hover/focus where applicable';
      n.state_matrix_template='conservative-nine-state-v1';n.runtime_status='pending';
    }
    definitions.push({id,source:file,component:name,line:line(sf,fn),end_line:sf.getLineAndCharacterOfPosition(fn.end).line+1,owners:owners(file,name),observation:'source-observed',discovery_review:'AST structural extraction; semantic reachability pending except source-annotations readbacks',categories:[...new Set([...native.flatMap(n=>n.categories),...(/Dialog|Drawer|Modal/.test(name)?['named-dialog-or-drawer']:[]),...(/Chart/.test(name)?['named-chart']:[]),...(/Tooltip/.test(name)?['named-tooltip']:[])])].sort(),jsx_calls:calls,native_surfaces:native,hooks,render_conditions:branches,state_matrix_template:'conservative-nine-state-v1',fixture_requirements:{base:'Deterministic route/store/API seed; render this component and all source-listed conditions; repeated rows require >=2 distinct identities',async:hooks.some(h=>h.call.includes('useEffect'))?'Delayed/success/error/out-of-order/cancelled mock responses; no live requests':'Inspect parent async props before marking async states N/A',persistence:'Isolated storage seed including current/legacy/invalid; sanitized before/after reload read-back; no unrelated storage'},runtime_status:'pending'});
  }
}
definitions.sort((a,b)=>a.id.localeCompare(b.id));
const definitionsByFile=new Map();for(const d of definitions){if(!definitionsByFile.has(d.source))definitionsByFile.set(d.source,[]);definitionsByFile.get(d.source).push(d);}
const instances=[];
for(const e of entries){
  // These are route/component *requirements*, not claimed rendered DOM counts.
  for(const file of e.reachable_modules)for(const d of definitionsByFile.get(file)||[])instances.push({id:'instance:'+e.source+'::'+d.id,route_entry_id:e.id,definition_id:d.id,route:e.route,modes:e.route.startsWith('/screener')?screenerModes(e.route):['not-mode-specific'],numeric_lane_handoff:[...new Set([e.owners.numeric,d.owners.numeric])],source_reachability:'transitive-module candidate; conditional and symbol-level execution not certified',entry_action:d.source===e.source?'Visit entry; see native controls and conditional branches':`Visit ${e.route}; traverse jsx_calls/native_surfaces conditions from attached entries`,state_ids:config.states.map(s=>'instance:'+e.source+'::'+d.id+'::state:'+s.key),native_instance_expansion:'For each definition.native_surfaces n: ID = this.id + "::" + n.id; inherit route, conditions, fixture requirements and n.owners. State ID = native instance ID + "::state:" + template key. All remain pending.',runtime_status:'pending'});
}
function screenerModes(route){if(/step-[123]-|^\/screener$/.test(route))return ['options','stocks','prebreakout'];if(/step-4-prebreakout/.test(route))return ['prebreakout:prebreakout','prebreakout:pullback','prebreakout:fib'];if(/step-4-stocks|step-5-strategy|step-6-backtest|step-7-position/.test(route))return ['stocks'];return ['options'];}
const reachedGraph=graph.filter(g=>reachable.has(g.source));
const unresolved=[...dynamics.filter(d=>reachable.has(d.source)),...config.pending_discovery];
const allComponents=[...sources].filter(([f])=>f.startsWith('frontend/components/')&&f.endsWith('.tsx')).map(([f])=>f).sort();
const notReached=allComponents.filter(f=>!reachable.has(f));
const nativeInstanceCount=instances.reduce((n,i)=>n+definitions.find(d=>d.id===i.definition_id).native_surfaces.length,0);
const counts={source_route_entry_files:entries.length,entry_classifications:Object.fromEntries([...new Set(entries.map(e=>e.classification))].sort().map(k=>[k,entries.filter(e=>e.classification===k).length])),entry_file_kinds:Object.fromEntries([...new Set(entries.map(e=>e.kind))].sort().map(k=>[k,entries.filter(e=>e.kind===k).length])),reachable_source_modules:reachable.size,component_definitions:definitions.length,component_route_requirement_instances:instances.length,jsx_custom_component_calls:definitions.reduce((n,d)=>n+d.jsx_calls.length,0),native_surface_candidates:definitions.reduce((n,d)=>n+d.native_surfaces.length,0),native_route_requirement_instances_normalized:nativeInstanceCount,state_rows_normalized:config.states.length,component_state_requirement_ids:instances.length*config.states.length,native_state_requirement_ids_normalized:nativeInstanceCount*config.states.length,settings_sections:config.settings_sections.length,screener_modes:3,prebreakout_submodes:3,component_files_not_reached:notReached.length,unresolved_discovery_items:unresolved.length};
const inventory={schema_version:1,phase:'APP-AUDIT-INVENTORY',source_baseline:baseline,coverage_status:'incomplete-source-structural-discovery; semantic and runtime reconciliation pending',completion_claim:false,counting_contract:{definitions:'Named JSX-producing component functions in the transitive local module graph, including inline co-located components and SVG icons. One definition per file#component; not a count of dialogs.',instances:'One candidate route-entry/component pair including inherited layout and applicable slot roots. Transitive imports conservatively include unused exports and mutually exclusive branches. These are coverage requirements, not observed DOM instances.',native_surfaces:'Per-definition AST JSX occurrence metadata; repeated map rows remain one source occurrence, with conditions recording repetition. Dialog/table/tooltip categories can overlap. Attribute and class names are candidates, not semantic proof.',state_rows:'Normalized nine-row template applied to every route-instance. Each expanded logical row has the explicitly listed state_id, source evidence inherited from definition, owners from definition, and pending status from template. No applicable state is passed. No N/A assigned without semantic proof.',id_stability:'Repo-relative path#component IDs survive row ordering and line shifts; rename/move intentionally changes ID. Route-instance identity includes source entry (parallel slot does not collide with main URL). Multiple JSX callsites remain distinct by source line and conditions; runtime repeated instances need fixture identity suffixes.'},counts,owners:config.owners,state_matrix_templates:{'conservative-nine-state-v1':config.states},state_row_expansion:{instruction:'For each route_instances record, zip state_ids with the nine template rows; definition.owners apply, with persistence owner I for reload-restart. Status remains pending. This normalized join is lossless for state requirements; no Cartesian scenario coverage is claimed.'},route_entries:entries,definitions,route_instances:instances,import_graph:reachedGraph,semantic_readbacks:config.semantic_readbacks,settings_sections:config.settings_sections,screener_modes:config.screener_modes,pending_discovery:unresolved,component_files_not_reached:notReached};
const cssInputs=[];
inventory.counting_contract.native_ids='Every native candidate has its own stable source/component/content identity, owner, action and conditions. Native route instance ID = parent route-instance.id + "::" + native.id; native state ID appends "::state:" + template key. Native counts are separate from component definitions/instances and remain conservative candidates.';
inventory.state_row_expansion.native='For each route-instance, expand every referenced definition.native_surfaces using native_instance_expansion. Each native disclosure/control has nine independently identifiable pending state requirements; runtime can refine applicable scenarios or source-backed N/A.';
for(const file of reachable){const sf=sources.get(file);for(const node of descendants(sf,n=>ts.isImportDeclaration(n)&&ts.isStringLiteralLike(n.moduleSpecifier)&&n.moduleSpecifier.text.endsWith('.css'))){const spec=node.moduleSpecifier.text;const css=spec.startsWith('@/')?'frontend/'+spec.slice(2):path.posix.normalize(path.posix.dirname(file)+'/'+spec);if(fs.existsSync(path.join(root,css)))cssInputs.push(css);}}
const inputs=[...reachable,...cssInputs,...walkFiles(path.join(root,'backend/config')).filter(f=>/\.yaml$/.test(f)).map(rel),'frontend/package.json','frontend/package-lock.json','frontend/tsconfig.json','.python-version',rel(path.join(report,'source-annotations.json'))].filter((x,i,a)=>a.indexOf(x)===i).sort();
const treeLines=cp.execFileSync('git',['ls-tree','-r',baseline,'--','frontend','backend/config','.python-version'],{cwd:root,encoding:'utf8'}).trim().split(/\r?\n/);
const baselineBlobs=new Map(treeLines.map(x=>{const [meta,file]=x.split('\t');return [file,meta.split(' ')[2]];}));
const blobHash=bytes=>crypto.createHash('sha1').update(Buffer.from('blob '+bytes.length+'\0')).update(bytes).digest('hex');
const normalizedCheckouts=[];
for(const file of inputs.filter(f=>!f.startsWith('docs/'))){const bytes=fs.readFileSync(path.join(root,file));if(blobHash(bytes)===baselineBlobs.get(file))continue;const lf=Buffer.from(bytes.toString('utf8').replace(/\r\n/g,'\n'));if(blobHash(lf)!==baselineBlobs.get(file))throw new Error('Source/config differs from pinned application baseline: '+file);normalizedCheckouts.push(file);}
const baselineTree=cp.execFileSync('git',['ls-tree','-r','--name-only',baseline,'--','frontend/app'],{cwd:root,encoding:'utf8'}).trim().split(/\r?\n/).filter(f=>/\/(page|layout|default|loading|error|not-found)\.tsx$/.test(f)&&!f.includes('/__tests__/')).sort();
if(JSON.stringify(entryFiles)!==JSON.stringify(baselineTree))throw new Error('Independent git tree route entry census mismatch');
const provenance={schema_version:1,source_baseline:baseline,source_baseline_resolved:cp.execFileSync('git',['rev-parse',baseline],{cwd:root,encoding:'utf8'}).trim(),tooling:{node:process.version,typescript:ts.version,next:require(require.resolve('next/package.json',{paths:[front]})).version,react:require(require.resolve('react/package.json',{paths:[front]})).version,python:'3.11.9 (python --version observed before generation; no backend execution)',browser:'Not used by source discovery; Task 2 records its own browser/build provenance',backend_mode:'Not started or contacted by source discovery; Task 2 isolated mocked API only'},fixture_provenance:'No runtime fixture consumed by source discovery. Source/config bytes are hashed only; no credential/config payload values copied. Task 2 must hash actual fixtures separately.',independent_route_census:{method:'git ls-tree baseline frontend/app, filter entry basenames and exclude __tests__; compare exact ordered set with filesystem/AST census',count:baselineTree.length,match:true},generator_sha256:sha(fs.readFileSync(__filename)),source_and_config_hashes:inputs.map(file=>({source:file,sha256:sha(fs.readFileSync(path.join(root,file)))})),numeric_correctness:'Not evaluated: source evidence is discovery and lane handoff, never arithmetic/persistence certification.'};
const index=['# APP-AUDIT-INVENTORY source index','','Source baseline `'+baseline+'`. Generated with TypeScript AST, import resolution and independent Git-tree route census. Read `provenance.json` for exact input hashes and tool versions.','','**Incomplete:** structural discovery is reproducible; semantic reachability, dynamic instances and runtime state reconciliation remain pending. This report does not certify displayed numbers, orders or persistence. No exclusion is user-approved.','','## Counts (distinct units)','','```json',JSON.stringify(counts,null,2),'```','','Definitions include inline components/icons; instances are conservative route/component candidates, not DOM counts or a disclosure count. Nine pending state requirements apply to each instance through the normalized join documented in inventory.json. Native disclosures are occurrence metadata inside definitions; multiple categories may overlap.','','## Route entries','','| Entry ID / source | URL | Classification | Numeric owner |','| --- | --- | --- | --- |',...entries.map(e=>`| \`${e.source}\` | \`${e.route}\` | ${e.classification} | ${e.owners.numeric}; persistence I; presentation J |`),'','## Source readbacks','',...config.semantic_readbacks.flatMap(r=>['### '+r.topic,'',r.detail,'',...r.evidence.map(e=>'- `'+e.source+':'+e.line+'` — '+e.note),'']),'## Settings and modes','','| Setting key | Entry action | Component / owner |','| --- | --- | --- |',...config.settings_sections.map(s=>`| ${s.key} | ${s.entry_action} | ${s.component}; ${s.owner} / I / J |`),'',...config.screener_modes.map(m=>'- **'+m.mode+'**: '+m.detail),'','## Components and transitive coverage','','All local module edges and per-entry closures are in `inventory.json.import_graph` and `route_entries[].reachable_modules`. Each definition includes JSX calls/props, native controls, conditions (including map repetition), hooks, source ranges and fixture requirements. Settings local functions and child disclosures are retained; barrels/imports are conservative module closures, so unrendered exports may remain.','',...entries.map(e=>'- `'+e.source+'`: '+e.reachable_modules.length+' modules; '+instances.filter(i=>i.route_entry_id===e.id).length+' candidate component definitions; roots '+e.attached_entry_sources.map(s=>'`'+s+'`').join(', ')), '','## Outstanding discovery','','Every item below prevents an exhaustive/completed inventory claim. The full machine-readable list includes source evidence and disposition.','',...unresolved.map(p=>'- '+(p.id?'`'+p.id+'` — ':'')+(p.detail||p.reason)+(p.source?' (`'+p.source+(p.line?':'+p.line:'')+'`)':'')), '', '## Regeneration and focused verification','','From the repository root:','','```powershell','node docs/superpowers/audits/app-audit/APP-AUDIT-INVENTORY/generate-source-inventory.cjs','node docs/superpowers/audits/app-audit/APP-AUDIT-INVENTORY/generate-source-inventory.cjs --check','```','','`--check` compares all three generated files byte-for-byte, checks IDs/source ranges, the independently obtained baseline route census and normalized state cardinality. It does not convert pending semantic/runtime checks into passes. Read `source-annotations.json` for reviewed semantic statements and state fixtures.','','Runtime Task 2 owns separate artifacts and observations mapped to IDs, avoiding edits to generated files. A source-only component/instance record remains pending until evidence reconciles its entry conditions and states.',''];
provenance.baseline_file_validation={method:'Each tracked source/config byte sequence is compared to the baseline Git blob SHA-1; Windows CRLF-to-LF canonicalization accepted only when it produces the exact baseline blob. SHA-256 records retain actual checkout bytes.',validated_files:inputs.filter(f=>!f.startsWith('docs/')).length,crlf_canonicalized_files:normalizedCheckouts};
index.push('Native candidates each have stable IDs, source ranges, owners, entry actions/conditions and state templates. Expand native route/state requirements using `native_instance_expansion` on each route-instance. Fixture rows still need data identity suffixes; source occurrences are not production row counts.','', 'Focused contract verification: `node docs/superpowers/audits/app-audit/APP-AUDIT-INVENTORY/verify-source-inventory.cjs`. This separately checks filesystem route census and known redirect/private/slot/CSS/portal/imperative/lifecycle edge cases.','');
// Validate generated references independently of JSON serialization.
for(const [label,rows] of [['route',entries],['definition',definitions],['native',definitions.flatMap(d=>d.native_surfaces)],['instance',instances]])if(new Set(rows.map(x=>x.id)).size!==rows.length)throw new Error('Duplicate '+label+' IDs');
const defIDs=new Set(definitions.map(d=>d.id));const entryIDs=new Set(entries.map(e=>e.id));
for(const i of instances){if(!defIDs.has(i.definition_id)||!entryIDs.has(i.route_entry_id)||i.state_ids.length!==9)throw new Error('Broken normalized join');}
for(const d of definitions){if(!sources.has(d.source)||d.line<1||d.end_line>read(d.source).split('\n').length)throw new Error('Invalid source location');}
const outputs={'inventory.json':JSON.stringify(inventory,null,2)+'\n','provenance.json':JSON.stringify(provenance,null,2)+'\n','source-index.md':index.join('\n')};
for(const [name,body] of Object.entries(outputs)){const f=path.join(report,name);if(process.argv.includes('--check')){if(!fs.existsSync(f)||fs.readFileSync(f,'utf8')!==body)throw new Error('Generated file drift: '+name);}else fs.writeFileSync(f,body);}
process.stdout.write(JSON.stringify({validated:true,check:process.argv.includes('--check'),counts})+'\n');
