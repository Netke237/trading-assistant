'use strict';
const files = {
 'frontend/tsconfig.json': JSON.stringify({compilerOptions:{baseUrl:'.',paths:{'@/*':['*']},jsx:'preserve',moduleResolution:'bundler',module:'esnext'}}),
 'frontend/app/page.tsx': `import { Rail, Client } from '@/barrel'; import type { Ghost } from './ghost';
export default function Page(){return <><Rail/><Client/></>}`,
 'frontend/barrel.ts': `export { Rail } from './rail'; export { Client } from './client'; export type { Ghost } from './ghost';`,
 'frontend/rail.tsx': `export function Rail({children}:any){return <aside>{children}</aside>}
export function SectionCard({children}:any){return <section>{children}</section>}`,
 'frontend/client.tsx': `/* directive through comments */\n'use client';
import {Rail,SectionCard} from './rail'; import {api} from './lib/api'; import {useStore, useDynamic} from './lib/store';
export function Client({fromParent}:any){
 const state=useStore(s=>s); const snapshot=useStore.getState(); api.list(); api.item('A'); api["list"]();
 useDynamic(); fromParent(); const alias=api; alias.list();
 function Unrelated(){api.other(); return <em>nested</em>}
 return <><Rail/><SectionCard><button title="same">Same</button><button title="same">Same</button></SectionCard></>;
}
export function Other(){api.other();return <div/>}
export function Shadow(){const api={list(){}};api.list(); const useStore=()=>1;useStore();return <div/>}`,
 'frontend/lib/api.ts': `const BASE_URL='http://unused'; async function get(path:string){return fetch(BASE_URL+path)}
async function post(path:string){return fetch(BASE_URL+path,{method:'POST'})}
export const api={list:()=>get('/list'),item:(id:string)=>post(\`/item/\${id}\`),other:()=>get('/other'),dynamic:(x:string)=>get(x)};`,
 'frontend/lib/store.ts': `import {create} from 'zustand';import {persist} from 'zustand/middleware';const KEY='fixture-store';export const useStore=create()(persist(()=>({}),{name:KEY}));export const useDynamic=create()(persist(()=>({}),{name:globalThis.dynamic}));`,
};
const surface=(file,name,natives=[])=>({id:`surface:${file}#${name}`,source:file,component:name,native_surfaces:natives});
const button=(suffix)=>({id:`native:${suffix}`,tag:'button',attributes:[{name:'title',value:'"same"'}],text:'Same',conditions:[]});
const inventory={route_entries:[{id:'route:frontend/app/page.tsx',source:'frontend/app/page.tsx',attached_entry_sources:['frontend/app/page.tsx']}],definitions:[surface('frontend/app/page.tsx','Page'),surface('frontend/rail.tsx','Rail'),surface('frontend/rail.tsx','SectionCard'),surface('frontend/client.tsx','Client',[button('one'),button('two')]),surface('frontend/client.tsx','Other'),surface('frontend/client.tsx','Shadow')],route_instances:[]};
for(const d of inventory.definitions)inventory.route_instances.push({id:'instance:'+d.id,route_entry_id:inventory.route_entries[0].id,definition_id:d.id});
module.exports={files,inventory,sourceSha:'fixture-source',supplemental:{capabilities:[]}};
