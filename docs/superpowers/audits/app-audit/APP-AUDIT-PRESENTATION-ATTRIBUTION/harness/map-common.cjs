'use strict';
// All source/TS resolution is confined to this in-memory frozen file system.
const fs=require('node:fs');const path=require('node:path');const cp=require('node:child_process');const crypto=require('node:crypto');
const REPO=path.resolve(__dirname,'../../../../../..');
const ts=require(require.resolve('typescript',{paths:[path.join(REPO,'frontend')]}));
const BASELINE='4a74d186468afe0a7fc4c53e785b24b5c1f72b42';
const INVENTORY='docs/superpowers/audits/app-audit/APP-AUDIT-INVENTORY/inventory.json';
const SUPPLEMENTAL='docs/superpowers/audits/app-audit/APP-AUDIT-INVENTORY/supplemental-capability-contracts.json';
const sha=x=>crypto.createHash('sha256').update(x).digest('hex');
function canonical(x){if(Array.isArray(x))return x.map(canonical);if(x&&typeof x==='object')return Object.fromEntries(Object.keys(x).sort().map(k=>[k,canonical(x[k])]));return x;}
const json=x=>JSON.stringify(canonical(x),null,2)+'\n';
// Public input contract: {files: {[repoRelativePath]: utf8}, inventory, supplemental,
// sourceSha, inventoryBytes?, supplementalBytes?}. The CLI always uses this fixed baseline.
function loadFrozen(repo=REPO){
 const show=f=>cp.execFileSync('git',['show',`${BASELINE}:${f}`],{cwd:repo,maxBuffer:32*1024*1024,encoding:'utf8'});
 const names=cp.execFileSync('git',['ls-tree','-r','--name-only',BASELINE,'--','frontend'],{cwd:repo,encoding:'utf8'}).trim().split('\n').filter(f=>/\.(tsx?|json)$/.test(f)&&!f.includes('/node_modules/'));
 const files=Object.fromEntries(names.sort().map(f=>[f,show(f)]));
 const inventoryBytes=show(INVENTORY),supplementalBytes=show(SUPPLEMENTAL);
 return {files,inventory:JSON.parse(inventoryBytes),supplemental:JSON.parse(supplementalBytes),sourceSha:BASELINE,inventoryBytes,supplementalBytes};
}
const isFn=n=>ts.isFunctionDeclaration(n)||ts.isFunctionExpression(n)||ts.isArrowFunction(n)||ts.isMethodDeclaration(n);
function functionName(n){if(n.name&&ts.isIdentifier(n.name))return n.name.text;let p=n.parent;while(p&&(ts.isCallExpression(p)||ts.isParenthesizedExpression(p)||ts.isAsExpression(p)))p=p.parent;return p&&ts.isVariableDeclaration(p)&&ts.isIdentifier(p.name)?p.name.text:null;}
const compact=s=>s.replace(/\s+/g,' ').trim().slice(0,280);
function all(n,pred){const out=[];function visit(x){if(pred(x))out.push(x);ts.forEachChild(x,visit);}visit(n);return out;}
function context(input){
 const files=input.files,V='/__j1_frozen__/';const abs=f=>V+f;const rel=f=>f.startsWith(V)?f.slice(V.length):f;
 const host={fileExists:f=>Object.hasOwn(files,rel(f)),readFile:f=>files[rel(f)],directoryExists:d=>Object.keys(files).some(f=>abs(f).startsWith(d.replace(/\/$/,'')+'/')),getCurrentDirectory:()=>V+'frontend',getDirectories:()=>[],useCaseSensitiveFileNames:()=>true,realpath:x=>x};
 const raw=ts.parseConfigFileTextToJson('frontend/tsconfig.json',files['frontend/tsconfig.json']||'{}');if(raw.error)throw new Error('Invalid frozen tsconfig');
 const options=ts.convertCompilerOptionsFromJson(raw.config.compilerOptions||{},V+'frontend').options;Object.assign(options,{noLib:true,noEmit:true,incremental:false});
 const sources=new Map(Object.entries(files).filter(([f])=>/\.tsx?$/.test(f)).sort().map(([f,s])=>[f,ts.createSourceFile(abs(f),s,ts.ScriptTarget.Latest,true,f.endsWith('.tsx')?ts.ScriptKind.TSX:ts.ScriptKind.TS)]));
 const compilerHost={...host,getSourceFile:f=>sources.get(rel(f)),getDefaultLibFileName:()=>V+'__no_lib__.d.ts',writeFile:()=>{},getCanonicalFileName:f=>f,getNewLine:()=> '\n'};
 const program=ts.createProgram([...sources.keys()].map(abs),options,compilerHost),checker=program.getTypeChecker();
 function symbol(n){let s=checker.getSymbolAtLocation(n);const seen=new Set();while(s&&(s.flags&ts.SymbolFlags.Alias)&&!seen.has(s)){seen.add(s);s=checker.getAliasedSymbol(s);}return s;}
 const declarations=[];for(const [source,sf] of sources)for(const node of all(sf,isFn)){const name=functionName(node);if(name)declarations.push({source,sf,node,name});}
 function span(node){const sf=node.getSourceFile(),start=node.getStart(sf),end=node.getEnd(),p=sf.getLineAndCharacterOfPosition(start);return {source:rel(sf.fileName),start,end,line:p.line+1,column:p.character+1,sha256:sha(sf.text.slice(start,end))};}
 function resolveDefinition(d){const found=declarations.filter(x=>x.source===d.source&&x.name===d.component);return found.length===1?{status:'resolved',span:span(found[0].node),node:found[0].node}:{status:'unresolved-source',reason:found.length?'ambiguous-declaration':'missing-declaration'};}
 const modules=[...sources].map(([source,sf])=>{
  const directives=[];for(const n of sf.statements){if(!ts.isExpressionStatement(n)||!ts.isStringLiteral(n.expression))break;directives.push(n.expression.text);}
  const edges=[];for(const n of all(sf,n=>ts.isImportDeclaration(n)||ts.isExportDeclaration(n)||ts.isCallExpression(n)&&((n.expression.kind===ts.SyntaxKind.ImportKeyword)||ts.isIdentifier(n.expression)&&n.expression.text==='require'))){
   let expr=n.moduleSpecifier||n.arguments?.[0];let specifier=expr&&ts.isStringLiteral(expr)?expr.text:null;
   if(!expr&&ts.isExportDeclaration(n))continue;
   const clause=n.importClause;const elements=clause?.namedBindings?.elements||n.exportClause?.elements;
   const typeOnly=!!n.isTypeOnly||!!clause?.isTypeOnly||!!elements?.length&&elements.every(e=>e.isTypeOnly)&&!clause?.name;
   const resolved=specifier?ts.resolveModuleName(specifier,abs(source),options,host).resolvedModule:null;
   const target=resolved?rel(resolved.resolvedFileName):null;
   edges.push({specifier,kind:typeOnly?'type-only':ts.isCallExpression(n)?'dynamic-runtime':ts.isExportDeclaration(n)?'re-export':'import',status:typeOnly?'type-only':target&&sources.has(target)?'resolved-runtime':'unresolved-runtime',target:target&&sources.has(target)?target:null,span:span(n),reason:!typeOnly&&!(target&&sources.has(target))?'outside-frozen-program-or-dynamic-specifier':null});
  }
  return {source,sha256:sha(sf.text),explicit_client:directives.includes('use client'),directives,edges};
 });
 const moduleByFile=new Map(modules.map(x=>[x.source,x]));
 function closure(roots,stopClient=false){const visited=new Set(),queue=[...roots];while(queue.length){const f=queue.shift();if(visited.has(f)||!moduleByFile.has(f))continue;visited.add(f);const m=moduleByFile.get(f);if(stopClient&&m.explicit_client)continue;for(const e of m.edges)if(e.status==='resolved-runtime')queue.push(e.target);}return [...visited].sort();}
 const inputs=Object.entries(files).sort().map(([source,bytes])=>({source,sha256:sha(bytes)}));
 const provenance={source_sha:input.sourceSha,input_hashes:inputs,inventory_sha256:sha(input.inventoryBytes||json(input.inventory)),supplemental_sha256:sha(input.supplementalBytes||json(input.supplemental)),typescript_version:ts.version};
 return {ts,files,sources,checker,symbol,declarations,span,resolveDefinition,modules,moduleByFile,closure,provenance,rel};
}
function cli(generate){const args=process.argv.slice(2);let repo=REPO,out;for(let i=0;i<args.length;i++){if(args[i]==='--repo')repo=path.resolve(args[++i]);else if(args[i]==='--out')out=path.resolve(args[++i]);else throw new Error('Usage: node <map>.cjs [--repo PATH] [--out FILE]');}const result=json(generate(loadFrozen(repo)));if(out)fs.writeFileSync(out,result);else process.stdout.write(result);}
module.exports={ts,REPO,BASELINE,sha,json,canonical,loadFrozen,context,isFn,functionName,all,compact,cli};
