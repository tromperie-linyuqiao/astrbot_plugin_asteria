/* Extend the existing settings/phone views; one API and one current scope. */
(function(){
'use strict';
const modelRoot=document.getElementById('model-routing-mount'),phoneRoot=document.getElementById('phone-status-mount');
const models=window.TLSModelRouting&&modelRoot?window.TLSModelRouting.mount(modelRoot,{api}):null;
const phone=window.TLSPhoneStatus&&phoneRoot?window.TLSPhoneStatus.mount(phoneRoot,{api,getScope:()=>state.scope}):null;
function activate(view){
 if(view==='config'){models?.activate();window.TLSMemoryStrategyPanel?.activate();}
 if(view==='phone_service'){phone?.setScope(state.scope);phone?.activate();}
}
const original=setView;setView=function(view){const result=original(view);activate(view);return result;};
const reset=resetNativeScopedViews;resetNativeScopedViews=function(){const result=reset();phone?.setScope(state.scope);if(state.view==='phone_service')phone?.activate();return result;};
activate(state.view);
})();
