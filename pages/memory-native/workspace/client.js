/** 星栖 Asteria workspace. Credited feature/view routines retained; transport, module state and startup owned by Asteria.
 * See docs/system/FRONTEND_PROVENANCE.md and upstream source notices. */
import {AsteriaPageClient,currentBridge} from './page-runtime.js';
const client=new AsteriaPageClient('memory',{allowHttp:true});
export function getBridge(){return currentBridge();}
export function apiGet(route){return client.get(route);}
export function apiPost(route,body={}){return client.post(route,body);}
export function apiRequest(route,options={}){return client.request(route,options);}
