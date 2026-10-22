// Recreate provenance hashes after browser capture and documentation changes.
const fs=require('fs'),path=require('path'),crypto=require('crypto'),cp=require('child_process');
const root=path.resolve(__dirname,'../../../../../../..');
const captured=JSON.parse(fs.readFileSync(path.join(__dirname,'output.json'),'utf8'));
const sha=b=>crypto.createHash('sha256').update(b).digest('hex');
const files=['frontend/lib/searchProfilesStore.ts','frontend/lib/settingsStore.ts','frontend/lib/theme.ts','frontend/components/ThemeProvider/index.tsx','frontend/components/StoreHydration/index.tsx','frontend/components/atoms/ModeToggle/index.tsx','frontend/components/organisms/SearchProfileBar/index.tsx','frontend/components/molecules/SaveProfileDialog/index.tsx','frontend/app/(frame)/settings/page.tsx','docs/search-profiles/import-search-profiles.js','docs/search-profiles/search-profiles-export.json','frontend/node_modules/zustand/middleware.js'];
const sourceFiles=files.map(file=>{
 const hash=sha(fs.readFileSync(path.join(root,file))),row={path:file,sha256:hash};
 if(!file.includes('/node_modules/')){for(const [name,commit] of [['captured',captured.source_sha],['original',captured.original_source_sha]]){row[name+'_commit_sha256']=sha(cp.execFileSync('git',['show',commit+':'+file],{cwd:root}));row['matches_'+name+'_commit']=row[name+'_commit_sha256']===hash;}}
 return row;
});
const artifacts=['browser.cjs','manifest.cjs','output.json','coverage.md','findings.md'].map(file=>({path:file,sha256:sha(fs.readFileSync(path.join(__dirname,file)))}));
const manifest={captured_source_sha:captured.source_sha,original_source_sha:captured.original_source_sha,versions:captured.versions,totals:captured.totals,sourceFiles,artifacts,note:'Manifest excludes its own hash. Source worktree hashes must match captured commit; original hash comparisons disclose the baseline difference. No product files changed by this ticket.'};
if(sourceFiles.some(f=>f.matches_captured_commit===false))throw Error('Source worktree drifted from captured commit; do not publish as exact source');
fs.writeFileSync(path.join(__dirname,'hashmanifest.json'),JSON.stringify(manifest,null,2)+'\n');
console.log(JSON.stringify({sourceFiles:sourceFiles.length,artifacts:artifacts.length,totals:captured.totals}));
