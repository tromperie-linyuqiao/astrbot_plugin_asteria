"""Independent small local-appearance boundaries; no APK build, device or network."""
from pathlib import Path
import subprocess
import shutil
import json

ROOT = Path(__file__).resolve().parents[3]
CLIENT = ROOT / 'client' / 'asteria-chat'


def test_actual_native_geometry_policy_rejects_extreme_source_bounds(tmp_path):
    jdk = Path.home() / 'AppData/Local/Programs/Microsoft/jdk-17.0.10.7-hotspot/bin'
    policy = CLIENT / 'android/src/com/asteria/chat/AppearanceImagePolicy.java'
    harness = tmp_path / 'IndependentAppearanceGeometry.java'
    harness.write_text('''
import com.asteria.chat.AppearanceImagePolicy;
public final class IndependentAppearanceGeometry {
    static void ok(boolean value) { if (!value) throw new AssertionError(); }
    static void bad(Runnable action) {
        try { action.run(); } catch (IllegalArgumentException expected) { return; }
        throw new AssertionError("extreme source or kind unexpectedly accepted");
    }
    public static void main(String[] args) {
        bad(() -> AppearanceImagePolicy.sample(Integer.MAX_VALUE, Integer.MAX_VALUE));
        bad(() -> AppearanceImagePolicy.sample(16385, 1));
        bad(() -> AppearanceImagePolicy.sample(8001, 8000));
        bad(() -> AppearanceImagePolicy.sample(0, 10));
        bad(() -> AppearanceImagePolicy.kind("attachment"));
        ok(AppearanceImagePolicy.sample(8000, 8000) == 4);
        ok(AppearanceImagePolicy.sample(16384, 1) == 8);
        ok(AppearanceImagePolicy.decodedSafe(2048, 2048));
        ok(!AppearanceImagePolicy.decodedSafe(2049, 2048));
        ok(!AppearanceImagePolicy.decodedSafe(Integer.MAX_VALUE, 2));
        int[] avatar = AppearanceImagePolicy.output("avatar", 1, 2048);
        ok(avatar[0] == 256 && avatar[1] == 256);
        int[] background = AppearanceImagePolicy.output("background", 2048, 1);
        ok(background[0] == 1280 && background[1] == 1);
        ok(AppearanceImagePolicy.MAX_INPUT_BYTES == 8388608);
        ok(AppearanceImagePolicy.MAX_OUTPUT_BYTES == 524288);
        System.out.println("independent geometry boundary passed");
    }
}
''', encoding='utf-8')
    compile_result = subprocess.run([str(jdk / 'javac.exe'), '-encoding', 'UTF-8',
        '-d', str(tmp_path), str(policy), str(harness)], capture_output=True, text=True, timeout=25)
    assert compile_result.returncode == 0, compile_result.stderr
    executed = subprocess.run([str(jdk / 'java.exe'), '-cp', str(tmp_path),
        'IndependentAppearanceGeometry'], capture_output=True, text=True, timeout=10)
    assert executed.returncode == 0, executed.stderr
    assert executed.stdout.strip() == 'independent geometry boundary passed'


NODE_HARNESS = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync(process.argv[2], 'utf8');
class Element {
  constructor() { this.value=''; this.hidden=false; this.open=false; this.textContent=''; this.children=[];
    this.style={}; this.dataset={}; this.classList={toggle(){}}; }
  addEventListener() {} setAttribute() {} focus() {} remove() {} scrollIntoView() {}
  showModal() { this.open=true; } close() { this.open=false; }
  replaceChildren(...v) { this.children=v; } append(...v) { this.children.push(...v); }
  querySelectorAll() { return []; }
}
function makeContext(shared) {
  const elements=new Map(); const calls=[];
  const context={assert, URL, console,
    setTimeout(){return 1;}, clearTimeout(){}, requestAnimationFrame(callback){callback();},
    localStorage:{ getItem(k){return shared.data.has(k)?shared.data.get(k):null;},
      setItem(k,v){if(shared.quota)throw Error('QuotaExceededError');shared.data.set(k,String(v));},
      removeItem(k){if(shared.quota)throw Error('QuotaExceededError');shared.data.delete(k);} },
    document:{getElementById(k){if(!elements.has(k))elements.set(k,new Element());return elements.get(k);},
      querySelector(){return new Element();},querySelectorAll(){return [];},createElement(){return new Element();},addEventListener(){}},
    window:{addEventListener(){},AsteriaChat:{request(){throw Error('unexpected network request');},
      getConfig(){return '{}';},chooseAppearanceImage(id,kind){calls.push({id,kind});},
      chooseAttachment(){throw Error('appearance crossed into attachment upload');}}},
    testStorage:shared, testCalls:calls};
  vm.createContext(context); vm.runInContext(source,context);
  vm.runInContext("state.server='https://example.invalid';state.username='fixture-user';state.authenticated=true;state.bridgeAvailable=true;state.sessions=[{session_id:'a'},{session_id:'b'}];state.activeId='a';",context);
  return context;
}
const shared={data:new Map(),quota:false};
const context=makeContext(shared);
context.freshContext=()=>makeContext(shared);
context.freshAppearance=()=>vm.runInContext("currentAppearance()",makeContext(shared));
(async()=>{await vm.runInContext('(async()=>{'+process.argv[3]+'})()',context);console.log('appearance independent passed');})()
.catch(error=>{console.error(error.stack);process.exitCode=1;});
"""


def run_web(tmp_path, checks):
    harness = tmp_path / 'appearance-independent.cjs'
    harness.write_text(NODE_HARNESS, encoding='utf-8')
    completed = subprocess.run([shutil.which('node'), str(harness),
        str(CLIENT / 'web/app.js'), checks], capture_output=True, text=True, timeout=20)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == 'appearance independent passed'


def test_real_web_scope_persistence_reset_and_refresh(tmp_path):
    run_web(tmp_path, r"""
const scope=appearanceScope();assert.ok(scope);
openAppearance();$('appearance-name').value='local name';assert.equal(saveAppearance({preventDefault(){}}),true,$('appearance-error').textContent);
assert.equal(readAppearance(scope).displayName,'local name');
const saved=testStorage.data.get(scope.key);
openAppearance();resetAppearance();cancelAppearance();assert.equal(testStorage.data.get(scope.key),saved);
state.activeId='b';assert.notEqual(appearanceScope().key,scope.key);assert.equal(currentAppearance().displayName,'');
state.activeId='a';state.username='different-user';assert.notEqual(appearanceScope().key,scope.key);assert.equal(currentAppearance().displayName,'');
state.username='fixture-user';state.server='https://different.invalid';assert.notEqual(appearanceScope().key,scope.key);
const restored=freshContext();assert.equal(restored.document.getElementById('appearance-dialog').open,false);
assert.equal(freshAppearance().displayName,'local name');
""")


def test_real_web_quota_failure_does_not_apply_or_claim_success(tmp_path):
    run_web(tmp_path, r"""
const scope=appearanceScope();openAppearance();$('appearance-name').value='original';assert.equal(saveAppearance({preventDefault(){}}),true);
const saved=testStorage.data.get(scope.key);openAppearance();$('appearance-name').value='unpersisted';testStorage.quota=true;
assert.equal(saveAppearance({preventDefault(){}}),false);assert.equal(testStorage.data.get(scope.key),saved);
assert.equal(currentAppearance().displayName,'original');assert.equal($('appearance-dialog').open,true);
assert.equal($('appearance-error').hidden,false);assert.match($('appearance-error').textContent,/无法保存/);
""")


def test_real_web_picker_cancel_stale_scope_and_attachment_lock(tmp_path):
    run_web(tmp_path, r"""
openAppearance();let pending=chooseAppearanceImage('avatar');assert.equal(testCalls.length,1);
receive(testCalls[0].id,{status:200,body:{cancelled:true}});await pending;
assert.equal(state.appearanceEditing.draft.avatar,null);assert.equal(state.appearanceBusy,false);
state.attaching=true;await chooseAppearanceImage('background');assert.equal(testCalls.length,1);state.attaching=false;
pending=chooseAppearanceImage('avatar');assert.equal(testCalls.length,2);const old=state.appearanceEditing;
state.activeId='b';receive(testCalls[1].id,{status:200,body:{kind:'avatar',width:256,height:256,data_url:'data:image/jpeg;base64,/9j/AAAA'}});await pending;
assert.equal(old.draft.avatar,null);assert.equal(state.appearanceBusy,false);assert.equal(testStorage.data.size,0);
state.activeId='a';openAppearance();pending=chooseAppearanceImage('background');cancelAppearance();
receive(testCalls[2].id,{status:200,body:{kind:'background',width:1,height:1,data_url:'data:image/jpeg;base64,/9j/AAAA'}});await pending;
assert.equal(state.appearanceEditing,null);assert.equal(state.appearanceBusy,false);assert.equal(testStorage.data.size,0);
""")
