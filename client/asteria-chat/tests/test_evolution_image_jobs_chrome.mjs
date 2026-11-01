/* One concentrated Chrome run. Actual shipped/current modules; all API,
   lifecycle and Native-completion events below are explicitly isolated fixtures. */
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
const require=createRequire(import.meta.url),{chromium}=require('playwright');
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..'),out=process.argv[2]||path.join(root,'../../.runtime/evolution-image-jobs');
await fs.mkdir(out,{recursive:true});
const html=(await fs.readFile(path.join(root,'web/index.html'),'utf8')).replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi,'');
const current=await fs.readFile(path.join(root,'web/chat-image-jobs.js'),'utf8');
const id='b'.repeat(64),config={available:true,authorized:true,size:'832x1216',configured_daily_limit:3,reference_configured:true};
const job=(state='pending',revision=1,extra={})=>({id,state,revision,authority:'server_job_state',source:'user_request',purpose:'chat',parent_message_id:'101',message_id:state==='stored'?'202':null,request_id:'fixture-original-001',updated_at:1800000000+revision,reason:state==='stored'?'sdk_history_saved':state==='unknown'?'provider_outcome_unknown':'accepted',can_retry:false,...extra});
const response=jobs=>({status:config,jobs,request_lookup:null});
const checks=[],browser=await chromium.launch({headless:true,executablePath:process.env.ASTERIA_CHROME_PATH || undefined});
async function settle(){await new Promise(resolve=>setTimeout(resolve,35));}
async function harness(module=current){
  const context=await browser.newContext({viewport:{width:390,height:844}}),page=await context.newPage(),calls=[],views=[],errors=[];
  const fixture={onGet:()=>response([job()]),onPost:body=>({lost:true}),getCount:0};
  page.on('pageerror',error=>errors.push(error.message));
  await page.exposeBinding('fixtureApi',async(_,q)=>{calls.push(q);return q.method==='GET'?fixture.onGet(++fixture.getCount,q.route):fixture.onPost(q.body);});
  await page.exposeBinding('fixtureView',(_,messageId)=>{views.push(messageId);return {opened:true};});
  await page.addInitScript(()=>{
    window.state={authenticated:true,server:'https://fixture.invalid',username:'owner',activeId:'owned',messages:[{id:'101|saved',serverId:101,role:'user',text:'咖啡馆的画面',delivery:'confirmed'}]};
    window.chatAuthEpoch=1;window.fixtureForeground=true;window.fixtureOnline=true;window.recoveryForeground=()=>fixtureForeground;
    Object.defineProperty(document,'hidden',{get:()=>!fixtureForeground});Object.defineProperty(navigator,'onLine',{get:()=>fixtureOnline});
    window.pref=value=>'asteria-chat.'+value;window.showNotice=()=>{};window.errorText=error=>error.message;window.hideMoreMenu=()=>{};
    window.ChatComposer={closePanel(){}};window.ChatMessageNavigation={open:id=>fixtureView(id)};
    let now=1800000000000,serial=0;const timers=new Map();Date.now=()=>now;
    window.setTimeout=(fn,delay)=>{const id=++serial;timers.set(id,{fn,at:now+Number(delay||0)});return id;};window.clearTimeout=id=>timers.delete(id);
    window.fixtureAdvance=ms=>{now+=ms;for(let turns=0;turns<100;turns++){const next=[...timers].filter(([,value])=>value.at<=now).sort((a,b)=>a[1].at-b[1].at)[0];if(!next)break;timers.delete(next[0]);next[1].fn();}};
    window.fixtureNativeActive=0;window.fixtureNativeMax=0;window.fixtureLateNative=null;
    window.apiClient={json:async(method,route,body,options)=>{
      const reading=method==='GET';if(reading){fixtureNativeActive++;fixtureNativeMax=Math.max(fixtureNativeMax,fixtureNativeActive);}
      let done=false;const complete=()=>{if(done)return;done=true;if(reading)fixtureNativeActive--;options?.onNativeComplete?.();};
      try{const value=await fixtureApi({method,route,body});
        if(value?.timeout){fixtureLateNative=complete;throw Object.assign(Error('模拟网页超时、Native尚未结束'),{nativeCompletionUnknown:true});}
        complete();if(value?.failure)throw Object.assign(Error('模拟服务器暂不可读取'),{status:value.failure});
        if(value?.lost)throw Error('模拟图片提交回执丢失');return value;
      }catch(error){if(!error.nativeCompletionUnknown)complete();throw error;}
    }};
  });
  await page.route('https://fixture.invalid/**',async route=>{const name=new URL(route.request().url()).pathname.slice(1)||'index.html';
    try{await route.fulfill({body:name==='index.html'?html:name==='chat-image-jobs.js'?module:await fs.readFile(path.join(root,'web',name)),contentType:name.endsWith('.js')?'text/javascript':name.endsWith('.css')?'text/css':'text/html'});}
    catch{await route.fulfill({status:404,body:'fixture asset missing'});}});
  const boot=async()=>{await page.goto('https://fixture.invalid/');await page.addScriptTag({url:'https://fixture.invalid/chat-image-jobs.js'});await page.evaluate(()=>document.dispatchEvent(new Event('DOMContentLoaded')));};
  await boot();const open=async()=>{await page.evaluate(()=>ChatImageJobs.open());await settle();};
  const advance=async ms=>{await page.evaluate(ms=>fixtureAdvance(ms),ms);await settle();};
  return {context,page,fixture,calls,views,errors,open,advance,boot,get gets(){return calls.filter(row=>row.method==='GET').length;},get posts(){return calls.filter(row=>row.method==='POST').length;}};
}
try{
  {
    const h=await harness();h.fixture.onGet=count=>response([job(count===1?'pending':count===2?'generating':'stored',count)]);
    await h.page.locator('#draft').fill('下一句话草稿');assert.equal(await h.page.locator('#draft').inputValue(),'下一句话草稿');await h.open();await h.page.locator('#image-request-prompt').fill('尚未提交的图片草稿');
    await h.advance(5000);assert.equal(h.gets,2);assert.match(await h.page.locator('#image-job-list').textContent(),/正在生成/);
    await h.advance(5000);assert.equal(h.gets,3);assert.match(await h.page.locator('#image-job-list').textContent(),/服务器已保存/);
    await h.advance(30000);assert.equal(h.gets,3);assert.equal(h.posts,0);assert.equal(await h.page.locator('#draft').inputValue(),'下一句话草稿');assert.equal(await h.page.locator('#image-request-prompt').inputValue(),'尚未提交的图片草稿');
    await h.page.getByRole('button',{name:'同步并查看图片',exact:true}).click();await settle();assert.deepEqual(h.views,['202']);
    assert.equal(await h.page.locator('#draft').inputValue(),'下一句话草稿');assert.equal(await h.page.evaluate(()=>fixtureNativeMax),1);
    checks.push('visible pending task follows GET-only progression to stored, stops after completion, and opens exact real-message reference through existing navigation without changing text/image drafts');await h.context.close();
  }
  {
    const h=await harness();await h.open();await h.page.locator('#image-request-prompt').fill('本会话的画面草稿');await h.page.locator('#image-request-purpose').selectOption('roleplay');
    await h.page.getByRole('button',{name:'关闭图片任务',exact:true}).click();const closed=h.gets;await h.advance(20000);assert.equal(h.gets,closed);
    await h.page.evaluate(()=>{state.activeId='other';ChatImageJobs.scopeChanged();state.activeId='owned';ChatImageJobs.scopeChanged();});await h.open();
    assert.equal(await h.page.locator('#image-request-prompt').inputValue(),'本会话的画面草稿');assert.equal(await h.page.locator('#image-request-purpose').inputValue(),'roleplay');
    await h.page.evaluate(()=>{fixtureForeground=false;ChatImageJobs.foregroundChanged();});const hidden=h.gets;await h.advance(20000);assert.equal(h.gets,hidden);
    await h.page.evaluate(()=>{fixtureForeground=true;ChatImageJobs.foregroundChanged();});await settle();assert.equal(h.gets,hidden+1);
    await h.page.evaluate(()=>{fixtureOnline=false;dispatchEvent(new Event('offline'));});const offline=h.gets;await h.advance(20000);assert.equal(h.gets,offline);
    await h.page.evaluate(()=>{fixtureOnline=true;dispatchEvent(new Event('online'));});await settle();assert.equal(h.gets,offline+1);
    await h.boot();await h.open();assert.equal(await h.page.locator('#image-request-prompt').inputValue(),'本会话的画面草稿');assert.equal(await h.page.locator('#image-request-purpose').inputValue(),'roleplay');
    checks.push('close/background/offline stop new reads; foreground/online resume once; picture draft/purpose survive scope switch and page reload');await h.context.close();
  }
  {
    const h=await harness();let release;h.fixture.onGet=count=>count===2?new Promise(resolve=>{release=resolve;}):response([job()]);await h.open();await h.advance(5000);
    assert.equal(h.gets,2);await h.page.evaluate(()=>{ChatImageJobs.read({manual:true});ChatImageJobs.foregroundChanged();});await settle();assert.equal(h.gets,2);
    await h.page.evaluate(data=>ChatImageJobs.streamEvent(data),job('stored',9));release(response([job('generating',2)]));await settle();
    assert.match(await h.page.locator('#image-job-list').textContent(),/服务器已保存/);assert.equal(await h.page.evaluate(()=>fixtureNativeMax),1);
    await h.advance(20000);assert.equal(h.gets,2);checks.push('one in-flight read only; delayed old GET cannot roll a newer stream revision back from stored to generating');await h.context.close();
  }
  {
    const h=await harness();h.fixture.onGet=count=>count===2?{timeout:true}:response([job()]);await h.open();await h.advance(5000);
    assert.match(await h.page.locator('#image-jobs-status').textContent(),/仍在等待原网络/);assert.equal(await h.page.locator('#image-jobs-refresh').isDisabled(),true);
    await h.page.evaluate(()=>{fixtureForeground=false;ChatImageJobs.foregroundChanged();fixtureForeground=true;ChatImageJobs.foregroundChanged();});await h.advance(30000);assert.equal(h.gets,2);
    await h.page.evaluate(()=>fixtureLateNative());await settle();await h.advance(30000);assert.equal(h.gets,2);assert.equal(await h.page.locator('#image-jobs-refresh').isDisabled(),false);
    await h.page.locator('#image-jobs-refresh').click();await settle();assert.equal(h.gets,3);assert.equal(await h.page.evaluate(()=>fixtureNativeMax),1);
    checks.push('45-second-style unknown Native completion retains real receive lock; resume cannot bypass it, and completion requires manual intent before a new read');await h.context.close();
  }
  {
    const h=await harness();await h.open();await h.page.locator('#image-request-prompt').fill('回执未知的原画面');await h.page.locator('#image-request-submit').click();await settle();
    assert.equal(h.posts,1);const original=h.calls.find(row=>row.method==='POST').body.request_id;await h.advance(5000);assert.equal(h.posts,1);
    assert(h.calls.filter(row=>row.method==='GET').at(-1).route.includes(encodeURIComponent(original)));
    await h.boot();await h.open();assert.equal(h.posts,1);assert.equal(await h.page.locator('#image-request-prompt').inputValue(),'回执未知的原画面');assert.equal(await h.page.locator('#image-request-submit').isDisabled(),true);
    assert(h.calls.filter(row=>row.method==='GET').at(-1).route.includes(encodeURIComponent(original)));
    checks.push('unknown paid POST nonce and image draft survive reload; automatic checks query the same nonce and never replay POST');await h.context.close();
  }
  {
    const h=await harness();h.fixture.onGet=count=>count===1?response([job()]):{failure:503};await h.open();await h.advance(5000);await h.advance(10000);await h.advance(20000);
    const failures=h.gets;assert.equal(failures,4);await h.advance(60000);assert.equal(h.gets,failures);assert.match(await h.page.locator('#image-jobs-status').textContent(),/连续核对未成功/);
    h.fixture.onGet=()=>response([job()]);await h.page.locator('#image-jobs-refresh').click();await settle();await h.advance(180001);const bounded=h.gets;await h.advance(60000);assert.equal(h.gets,bounded);assert.match(await h.page.locator('#image-jobs-status').textContent(),/发起预算/);
    h.fixture.onGet=()=>response([job('stored',10,{message_id:null})]);await h.page.locator('#image-jobs-refresh').click();await settle();
    assert.match(await h.page.locator('#image-job-list').textContent(),/未返回聊天消息编号/);assert.equal(await h.page.getByRole('button',{name:'同步并查看图片',exact:true}).count(),0);
    await h.page.screenshot({path:path.join(out,'image-jobs-phone-fixture.png')});await h.page.setViewportSize({width:390,height:360});
    const close=await h.page.getByRole('button',{name:'关闭图片任务',exact:true}).boundingBox();assert(close&&close.y>=0&&close.y+close.height<=360);assert(await h.page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await h.page.screenshot({path:path.join(out,'image-jobs-small-fixture.png')});assert.deepEqual(h.errors,[]);
    checks.push('three completed read failures back off then pause; launch-window budget is bounded; stored-without-message-ID exposes no dead view button; 390-wide short/normal Chrome view stays reachable');await h.context.close();
  }
  {
    const h=await harness();h.fixture.onGet=()=>response([]);await h.open();await h.page.locator('#image-request-prompt').fill('accepted nonce');await h.page.locator('#image-request-submit').click();await settle();
    const original=h.calls.find(row=>row.method==='POST').body.request_id;
    h.fixture.onGet=()=>({...response([job('stored',8,{request_id:'later-retry-002',attempt:2})]),request_lookup:{request_id:original,found:true,matched_attempt:1,job:job('stored',8,{request_id:'later-retry-002',attempt:2})}});
    await h.advance(5000);assert.equal(h.posts,1);assert.equal(await h.page.locator('#image-request-submit').isDisabled(),false);assert.match(await h.page.locator('#image-job-list').textContent(),/服务器已保存/);
    checks.push('server accepted-attempt lookup resolves original pending nonce even when the job now has a later retry nonce, without another POST');await h.context.close();
  }
  {
    const h=await harness();h.fixture.onGet=count=>response([job('stored',7,{message_id:count===1?null:'202'})]);await h.open();assert.equal(await h.page.getByRole('button',{name:'同步并查看图片',exact:true}).count(),0);
    await h.advance(5000);assert.equal(h.gets,2);assert.equal(await h.page.getByRole('button',{name:'同步并查看图片',exact:true}).count(),1);await h.advance(30000);assert.equal(h.gets,2);assert.equal(h.posts,0);
    checks.push('stored task missing a message identity continues bounded read-only reconciliation until the existing history reference appears');await h.context.close();
  }
  const result={passed:true,checks,real_chrome:true,api_and_lifecycle_fixture:true,native_completion_simulated:true,production:false,android:false,models:0,paid_images:0};
  await fs.writeFile(path.join(out,'evolution-image-jobs.safe.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
}finally{await browser.close();}
