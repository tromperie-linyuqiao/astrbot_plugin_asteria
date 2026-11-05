/** 星栖 Asteria workspace. Credited feature/view routines retained; transport, module state and startup owned by Asteria.
 * See docs/system/FRONTEND_PROVENANCE.md and upstream source notices. */
import {AsteriaPageClient,currentBridge,usableBridge} from './page-runtime.js';
const client=new AsteriaPageClient('companion',{allowHttp:()=>isDebugHttpMode()});
export function getBridge(){return currentBridge();}
export function isUsableBridge(bridge){return usableBridge(bridge);}
export function isDebugHttpMode(){return new URLSearchParams(location.search).get('debug_http')==='1';}
export async function getPageBridge(){return currentBridge()?client.bridge():null;}
export function fetchJson(route,options={}){return client.request(route,options);}
export function postJson(route,body){return client.post(route,body);}
