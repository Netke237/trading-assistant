/* Supplemental source requirements: joins by capability/route IDs; never runtime observations. */
const fs=require('fs'),path=require('path'),assert=require('assert/strict');
const chart='frontend/components/organisms/ChartOverlays/index.tsx',drawing='frontend/components/organisms/DrawingOverlays/index.tsx',indicator='frontend/components/molecules/IndicatorPanel/index.tsx',hoc='frontend/components/molecules/ContractScoreExplanation/index.tsx';
function generate(i,semantic,root) {
 const evidence=(source,anchor)=>{const lines=fs.readFileSync(path.join(root,source),'utf8').split(/\r?\n/);const index=lines.findIndex(l=>l.includes(anchor));assert(index>=0,'missing source anchor '+source+':'+anchor);return {source,line:index+1,end_line:index+1,anchor};};
 const E=(source,...anchors)=>anchors.map(a=>evidence(source,a));
 const spec=(key,fixture_contract,source_evidence,inheritance='intrinsic plus caller shared-state interactions')=>({key,fixture_contract,source_evidence,inheritance});
 const matrix=i.state_matrix_templates['conservative-nine-state-v1'].map(s=>s.key);
 const definitions=new Map(i.definitions.map(d=>[d.id,d]));
 const contracts=semantic.supplemental_local_capabilities.map(cap=>{
  const callers=cap.entry_call_ids.map(id=>semantic.jsx_occurrences.find(j=>j.id===id));
  const owners=cap.owners;
  const caller_source=callers.map(j=>({call_id:j.id,parent_definition_id:j.parent_definition_id,source:j.source,line:j.line,props:j.attributes,entry_conditions:definitions.get(j.parent_definition_id)?.render_conditions||[]}));
  const ranges=[{source:cap.source,line:cap.line,end_line:cap.end_line}];
  let states=[];let inherited_definition=null;
  if(cap.source===hoc) {
   const content=i.definitions.find(d=>d.source===hoc&&d.component==='ContractScoreExplanationContent'); assert(content);inherited_definition=content.id;
   ranges.push({source:content.source,line:content.line,end_line:content.end_line});
   for(const key of matrix) states.push(spec(key,`Mount React.memo(ContractScoreExplanationContent) through each Step6 expanded desktop/mobile contract explanation caller with id and contract; inherit ${content.id} ${key} fixture contract, including caller loading/empty/failure/reload and nested details. Memoized wrapper adds no independent DOM state; change contract object identity to require content recomputation.`,E(hoc,'React.memo(ContractScoreExplanationContent)','const exp = contract.explanation;','if (!exp || !validateExplanation(exp, contract.id))'),{definition_id:content.id,state_key:key}));
   states.push(spec('missing-invalid-explanation','Use contract.explanation absent then invalid for contract.id; expanded caller must show unavailable breakdown.',E(hoc,'if (!exp || !validateExplanation(exp, contract.id))','Explanation unavailable')));
   states.push(spec('blocked-and-zero-score','Use blocked outcome then valid PASS/CAUTION outcome; include score=0 and unrounded_score=0 versus null, partial components and nested explanation details; C owns formatted values and thresholds.',E(hoc,"exp.outcome === 'blocked'",'exp.unrounded_score != null','exp.score')));
   states.push(spec('memo-replacement','Replace selected contract with a distinct object/explanation while expanded; preserve contract.id match and compare visible score/status/thresholds to replacement fixture.',E(hoc,'React.memo(ContractScoreExplanationContent)','exp.score')));
  } else {
   assert([chart,drawing,indicator].includes(cap.source),'unclassified supplemental capability '+cap.id);
   const isChart=cap.source===chart,isDrawing=cap.source===drawing;
   const values=isChart?'signals/visibility/visible':isDrawing?'drawings':'type/data';
   const guard=isChart||isDrawing?'if (!chart || !mainSeries) return;':'if (!chart) return;';
   const effect=isChart?'[chart, mainSeries, signals, visibility, visible]':isDrawing?'[chart, mainSeries, drawings]':'[data, type]';
   const empty=isChart?'for (const signal of signals)':isDrawing?'diffDrawings(attached, drawings)':'data.length === 0';
   const refs=E(cap.source,guard,effect,empty,'return null;');
   const fixtures={
    normal:`Supply ready chart${isChart||isDrawing?' and Candlestick mainSeries':''}, populated ${values} through the recorded caller props; inspect imperative series/pane output, not component DOM (return null).`,
    'expanded-nested':`No intrinsic JSX disclosure (return null); inherit each caller's expanded-nested state, mounted chart children and toolbar/panel interactions, keeping ${values} live.`,
    empty:`Use ${isChart?'signals=[]':isDrawing?'drawings=[] after attachment':'data=[] before and after population'} with ready handles; inspect ${isChart?'zero attachments and previous detach':isDrawing?'removed old primitives via diffDrawings':'guard skips setData (does not clear existing series)'} and ancestor empty/loading chart states.`,
    loading:`Inherit caller data-fetch loading; separately mount chart=null${isChart||isDrawing?' or mainSeries=null':''} until ready; effect must not access unavailable handles. No intrinsic fetch/loading UI.`,
    'failed-cancelled':`Inherit caller fetch/error/cancel and route error boundary; ${isDrawing?'inject detach failure in production versus non-production (rethrows in dev)':'inspect caught cleanup failures'} during removal/unmount. No intrinsic error UI.`,
    'legacy-unsupported':`Inherit caller persisted legacy/unsupported recovery and domain validation before mounting typed ${values}; return-null component has no migration UI. Do not invent unsupported typed kinds as route fixtures.`,
    'zero-false-null-absent':isChart?'Separate chart=null, mainSeries=null, visible=false, visibility[kind]=false, signals=[]; numeric zero signal coordinates require H validation. Required signals/visibility/visible absent are not admitted Props, inherit caller absent-data recovery.':isDrawing?'Separate chart=null and mainSeries=null, drawings=[], zero drawing coordinates, drawing.visible=false (diffDrawings has no visibility filter); required drawings absent not admitted Props, inherit caller recovery.':'Separate chart=null, data=[], zero RSI/MACD/volume values and MACD histogram=0 boundary; required type/data absent not admitted Props, inherit caller recovery.',
    'stale-async':`Replace ${values} and chart handles after initial ready mount; inherit caller async race fixtures. Effect dependencies and cleanup are source requirements, not proof of numerical freshness.`,
    'reload-restart':`No intrinsic persist call; inherit caller I-owned store/API/browser reload and actual backend restart requirements; remount ready chart and recovered ${values} and inspect teardown/recreation. Real backend restart remains pending.`
   };
   states=matrix.map(key=>spec(key,fixtures[key],refs));
   states.push(spec('missing-chart','Mount caller with chart=null then ready chart; compare no handle access to ready output and ancestor loading state.',E(cap.source,guard)));
   if(isChart||isDrawing) states.push(spec('missing-main-series','Mount chart ready with mainSeries=null then ready Candlestick series; compare no attachment to ready output and captured cleanup.',E(cap.source,guard)));
   if(isChart) {
    states.push(spec('hidden-global','Attach populated signals then set structureVisible=false via ChartWorkspace visible prop; previous primitives detached before early return.',E(chart,'if (!visible) return;','series.detachPrimitive(p)')));
    states.push(spec('per-kind-visible','For each FVG, OrderBlock, BOS, CHoCH, Fibonacci, Divergence, Confluence, toggle structureVisibility[kind] independently with other kinds visible; inspect primitive identity/output for each kind.',E(chart,'if (!visibility[signal.kind]) continue;',"case 'FVG':","case 'OrderBlock':","case 'BOS':","case 'CHoCH':","case 'Fibonacci':","case 'Divergence':","case 'Confluence':")));
    for(const kind of ['FVG','OrderBlock','BOS','CHoCH','Fibonacci','Divergence','Confluence']) for(const visible of [true,false]) states.push(spec('kind-'+kind+'-'+(visible?'visible':'hidden'),`Use ready chart/mainSeries, structureVisible=true and a ${kind} signal with structureVisibility.${kind}=${visible}; retain other visible kinds and inspect only this kind's primitive attachment/detach and numerical output.`,E(chart,'if (!visibility[signal.kind]) continue;',`case '${kind}':`)));
    states.push(spec('replacement-teardown','Replace structureSignals then visibility or chart/mainSeries; unmount workspace. Compare old/new primitive attachments and detach identities, including cleanup failures caught; H output and I symbol/interval recovery pending.',E(chart,'series.detachPrimitive(p)','series.attachPrimitive(primitive)','return () => {')));
   } else if(isDrawing) {
    states.push(spec('drawing-kinds-and-visibility','Use one each hline, trendline, rect, text, arrow, arrow_up, arrow_down, circle, path with visible=true then false; actual caller only filters symbol/interval, diffDrawings does not filter visible. H/J must validate output rather than assume hidden.',E(drawing,"case 'hline':","case 'path':"), 'intrinsic makePrimitive helper plus caller symbol/interval filter'));
    for(const kind of ['hline','trendline','rect','text','arrow','arrow_up','arrow_down','circle','path']) states.push(spec('kind-'+kind,`Use a ${kind} drawing for current symbol/interval with visible=true then visible=false and zero coordinates; inspect constructor output and replacement. Neither caller filter nor diffDrawings filters visible; H/J owns whether primitive rendering hides it.`,E(drawing,`case '${kind}':`)));
    states.push(spec('drawing-diff-replacement','Use stable id same object, same id new object, removed id, new id, duplicate ids (last nextById wins), and symbol/interval switch using ChartWorkspace drawings.filter; inspect toAdd/toRemove/toUpdate and drawing identity.',E(drawing,'diffDrawings(attached, drawings)','entry.primitive.update(drawing)'), 'intrinsic diffDrawings helper plus caller filter'));
    states.push(spec('replacement-teardown','Replace chart/mainSeries, then unmount; cleanup detaches via captured optional mainSeries and clears attached map; inspect non-production detach exception versus production caught exception.',E(drawing,'mainSeries?.detachPrimitive(entry.primitive)','attached.clear();',"process.env.NODE_ENV !== 'production'")));
    ranges.push({source:'frontend/lib/chart/drawingOverlaysDiff.ts',line:20,end_line:47},{source:drawing,line:25,end_line:42});
   } else {
    for(const kind of ['rsi','macd','volume']) states.push(spec('type-'+kind,`Set activeIndicators to include ${kind}; CandlestickChart supplies indicatorData[type] and key chartVersion-type. Mount ready chart with typed ${kind} points, inspect pane series/data; replace data and switch kind.`,E(indicator,`type === '${kind}'`,'[chart, type]','[data, type]')));
    states.push(spec('replacement-teardown','Change chart/type or CandlestickChart chartVersion key then unmount; inspect old pane removal, seriesRef reset and recreated series. Empty data skips setData and may retain previous output.',E(indicator,'chart.removePane(paneIndexRef.current)','seriesRef.current = [];','data.length === 0')));
   }
  }
  return {capability_id:cap.id,source_range:ranges[0],supporting_source_ranges:ranges.slice(1),entry_call_ids:cap.entry_call_ids,caller_source,owners,inherited_definition_state_contract:inherited_definition?semantic.definition_state_contracts.find(d=>d.definition_id===inherited_definition):null,states:states.map(s=>({...s,id:cap.id+'/state:'+s.key,owners,caller_state_refs:callers.map(j=>({definition_id:j.parent_definition_id,state_key:matrix.includes(s.key)?s.key:'normal'})),correctness_status:'pending owning lane',runtime_status:'source requirement; not executed'}))};
 });
 const route_instances=[],route_state_requirements=[];
 for(const route of semantic.route_symbol_classification) for(const c of contracts.filter(c=>route.jsx_reachable_capability_ids.includes(c.capability_id))) {
  const id=route.route_entry_id+'::'+c.capability_id,entry=i.route_entries.find(e=>e.id===route.route_entry_id);
  const owners={...c.owners,numeric_lanes:[...new Set([...c.owners.numeric_lanes,entry.owners.numeric])].sort()};
  const rows=c.states.map(s=>({id:id+'/state:'+s.key,route_instance_id:id,route_entry_id:entry.id,capability_state_id:s.id,fixture_contract_ref:s.id,owners,correctness_status:'pending owning lane',runtime_status:'source requirement; not executed'}));
  route_instances.push({id,route_entry_id:entry.id,capability_id:c.capability_id,owners,entry_call_ids:c.entry_call_ids,state_requirement_ids:rows.map(r=>r.id)});route_state_requirements.push(...rows);
 }
 const native_state_inheritance=semantic.jsx_occurrences.filter(j=>j.kind==='native'&&contracts.some(c=>c.capability_id===j.parent_definition_id)).map(j=>({jsx_id:j.id,parent_capability_id:j.parent_definition_id,source:{source:j.source,line:j.line},state_ids:contracts.find(c=>c.capability_id===j.parent_definition_id).states.map(s=>s.id)}));
 return {schema_version:1,source_baseline:i.source_baseline,join:'inventory.json route_entries.id + semantic-classification.json supplemental_local_capabilities.id; additive route/state requirements, no replacement of historical inventory IDs',capability_state_contracts:contracts,route_instances,route_state_requirements,native_state_inheritance};
}
module.exports=generate;
