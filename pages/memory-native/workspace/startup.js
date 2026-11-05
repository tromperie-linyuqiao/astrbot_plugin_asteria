/** 星栖 Asteria workspace. Credited feature/view routines retained; transport, module state and startup owned by Asteria.
 * See docs/system/FRONTEND_PROVENANCE.md and upstream source notices. */

import {installWorkspaceShell} from './page-runtime.js';
import {init} from './navigation.js';

let started=false;
export function startWorkspace(){
  if(started)return;
  started=true;
  installWorkspaceShell('memory');
init();
}
