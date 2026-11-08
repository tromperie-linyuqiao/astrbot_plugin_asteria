package com.asteria.chat;

import android.app.*;
import android.content.*;
import android.content.pm.ServiceInfo;
import android.media.*;
import android.os.*;
import java.util.Arrays;
import java.util.function.BooleanSupplier;
import org.json.*;

/** User-started microphone foreground service. It never sends chat requests or stores recordings. */
public final class PhoneCallService extends Service {
    private static final String CHANNEL="texas-chat-call-microphone",MUTE="call_mute",END="call_end";
    private static final int ID=5307;
    interface Observer {void changed(JSONObject value);}
    private static volatile Active active;
    private static volatile Observer observer;
    private static final class Active {
        final String id,scope,session;final BooleanSupplier current;final int silence;final float threshold;
        volatile CallSession pipeline;volatile PhoneCallService service;volatile boolean ended;String finalMessage="通话已结束 · 麦克风已关闭";
        Active(String id,String scope,String session,BooleanSupplier current,int silence,float threshold){this.id=id;this.scope=scope;this.session=session;this.current=current;this.silence=silence;this.threshold=threshold;}
    }
    private Active owner;private PowerManager.WakeLock wake;private String lastNotification="";
    static void observe(Observer value){observer=value;}
    static boolean running(){Active a=active;return a!=null&&!a.ended&&(a.pipeline==null||a.pipeline.snapshot().active);}
    static void outputCurrent(boolean value){Active a=active;if(a!=null&&a.current.getAsBoolean()&&a.pipeline!=null)try{a.pipeline.output(value);}catch(Exception failed){a.pipeline.pause("声音播放已结束，请明确继续收音");}}
    static synchronized void begin(Context context,String id,String scope,String session,BooleanSupplier current,int silence,float threshold){
        if(active!=null)throw new IllegalStateException("请先结束当前通话");
        if(!id.matches("[a-zA-Z0-9_-]{8,100}"))throw new IllegalArgumentException("通话编号无效");
        Active next=new Active(id,scope,session,current,silence,threshold);active=next;
        try{context.startForegroundService(new Intent(context,PhoneCallService.class).putExtra("id",id));}
        catch(RuntimeException e){active=null;throw e;}
    }
    static JSONObject status(Context context,String scope){
        Active a=active;boolean ready=CallModelStore.ready(CallModelStore.directory(context));
        if(a==null||!a.scope.equals(scope))return object("ok",true,"active",false,"model_ready",ready,"message","通话未开始");
        JSONObject value=snapshot(a);put(value,"model_ready",ready);return value;
    }
    static void command(String id,String scope,String action,int sequence,boolean output)throws Exception {
        Active a=active;if(a==null||!a.id.equals(id)||!a.scope.equals(scope)||!a.current.getAsBoolean())throw new IllegalStateException("原通话已结束或会话已变化");
        if(action.equals("end")){end();return;}
        CallSession p=a.pipeline;if(p==null)throw new IllegalStateException("正在启动通话，请稍候");
        switch(action){case "mute":p.mute();break;case "resume":p.resume();break;case "hold":p.pause("聊天结果待确认，自动发送已暂停；请检查聊天后明确继续");break;case "ack":p.ack(sequence);break;case "output":p.output(output);break;default:throw new IllegalArgumentException("通话操作无效");}
    }
    static synchronized void end(){Active a=active;if(a==null||a.ended)return;a.ended=true;CallSession p=a.pipeline;if(p!=null)p.close();PhoneCallService service=a.service;if(service!=null)service.finish(a);else{active=null;emit(a,object("ok",true,"call_id",a.id,"session_id",a.session,"active",false,"message",a.finalMessage));}}
    private static JSONObject snapshot(Active a){
        CallSession.Snapshot s=a.pipeline==null?null:a.pipeline.snapshot();JSONArray turns=new JSONArray();if(s!=null)for(CallSession.Turn turn:s.turns)turns.put(object("sequence",turn.sequence,"text",turn.text));
        return object("ok",true,"call_id",a.id,"session_id",a.session,"active",s==null||s.active,"muted",s!=null&&s.muted,"held",s!=null&&s.held,"capturing",s!=null&&s.capturing,"output",s!=null&&s.output,"level",s==null?0:s.level,"message",s==null?"正在准备本机通话":s.message,"turns",turns);
    }
    private static void emit(Active a,JSONObject value){Observer listener=observer;if(listener!=null)listener.changed(value);}
    @Override public int onStartCommand(Intent intent,int flags,int startId){
        Active selected=active;
        if(intent!=null&&END.equals(intent.getAction())){if(selected!=null&&selected.id.equals(intent.getStringExtra("id")))end();return START_NOT_STICKY;}
        if(intent!=null&&MUTE.equals(intent.getAction())){if(selected!=null&&selected.id.equals(intent.getStringExtra("id"))&&selected.pipeline!=null)selected.pipeline.mute();return START_NOT_STICKY;}
        if(selected==null||intent==null||!selected.id.equals(intent.getStringExtra("id"))||!selected.current.getAsBoolean()){stopSelf();return START_NOT_STICKY;}
        if(owner==selected&&selected.pipeline!=null)return START_NOT_STICKY;
        owner=selected;owner.service=this;
        try{
            NotificationManager manager=getSystemService(NotificationManager.class);NotificationChannel channel=new NotificationChannel(CHANNEL,"电话模式收音状态",NotificationManager.IMPORTANCE_LOW);channel.setSound(null,null);manager.createNotificationChannel(channel);
            if(Build.VERSION.SDK_INT>=29)startForeground(ID,notification("正在准备离线收音"),ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE);else startForeground(ID,notification("正在准备离线收音"));
            wake=((PowerManager)getSystemService(POWER_SERVICE)).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,"AsteriaChat:UserPhoneMode");wake.setReferenceCounted(false);
            owner.pipeline=new CallSession(owner.current,Microphone::new,new CallSpeechEngine(CallModelStore.directory(this)),state->{
                if(active!=selected)return;
                update(state);emit(selected,snapshot(selected));if(!state.active)end();
            },owner.silence,owner.threshold);
            owner.pipeline.start();
        }catch(Throwable e){if(active==selected){selected.finalMessage="无法开始持续收音，请检查麦克风权限与离线模型";end();}}
        return START_NOT_STICKY;
    }
    private void update(CallSession.Snapshot state){
        String key=state.active+":"+state.muted+":"+state.held+":"+state.capturing+":"+state.output;
        synchronized(this){if(key.equals(lastNotification))return;lastNotification=key;}
        new Handler(Looper.getMainLooper()).post(()->{if(active!=owner||owner==null)return;if(state.active&&!state.muted&&!state.held&&!state.output){if(wake!=null&&!wake.isHeld())wake.acquire();}else if(wake!=null&&wake.isHeld())wake.release();getSystemService(NotificationManager.class).notify(ID,notification(state.capturing?"正在收音 · 停顿分句后自动发送":state.active?"已暂停收音 · 点此返回通话":"通话已结束"));});
    }
    private Notification notification(String text){
        PendingIntent open=PendingIntent.getActivity(this,ID,new Intent(this,MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
        Intent mute=new Intent(this,PhoneCallService.class).setAction(MUTE).putExtra("id",owner.id),end=new Intent(this,PhoneCallService.class).setAction(END).putExtra("id",owner.id);
        return new Notification.Builder(this,CHANNEL).setSmallIcon(android.R.drawable.ic_btn_speak_now).setContentTitle("Asteria Chat 电话模式").setContentText(text).setContentIntent(open).setOngoing(true).setOnlyAlertOnce(true).setCategory(Notification.CATEGORY_SERVICE)
            .addAction(new Notification.Action.Builder(null,"静音",PendingIntent.getService(this,ID+1,mute,PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE)).build())
            .addAction(new Notification.Action.Builder(null,"结束",PendingIntent.getService(this,ID+2,end,PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE)).build()).build();
    }
    private void finish(Active expected){new Handler(Looper.getMainLooper()).post(()->{if(owner!=expected)return;if(wake!=null&&wake.isHeld())wake.release();stopForeground(STOP_FOREGROUND_REMOVE);synchronized(PhoneCallService.class){if(active==expected)active=null;}emit(expected,object("ok",true,"call_id",expected.id,"session_id",expected.session,"active",false,"message",expected.finalMessage));stopSelf();});}
    @Override public void onTaskRemoved(Intent root){end();super.onTaskRemoved(root);}
    @Override public void onDestroy(){Active old=owner;if(active==old)end();if(wake!=null&&wake.isHeld())wake.release();super.onDestroy();}
    @Override public IBinder onBind(Intent intent){return null;}
    private static final class Microphone implements CallSession.Capture {
        private volatile boolean running;private AudioRecord recorder;
        @Override public synchronized void start(CallSession.Frames frames,Runnable failed){
            int min=AudioRecord.getMinBufferSize(16000,AudioFormat.CHANNEL_IN_MONO,AudioFormat.ENCODING_PCM_16BIT);if(min<=0)throw new IllegalStateException("设备不支持本机收音格式");
            recorder=new AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION,16000,AudioFormat.CHANNEL_IN_MONO,AudioFormat.ENCODING_PCM_16BIT,Math.max(min,3200));
            if(recorder.getState()!=AudioRecord.STATE_INITIALIZED){recorder.release();recorder=null;throw new IllegalStateException("麦克风未就绪");}
            recorder.startRecording();if(recorder.getRecordingState()!=AudioRecord.RECORDSTATE_RECORDING){close();throw new IllegalStateException("麦克风无法开始录音");}
            running=true;final AudioRecord source=recorder;
            new Thread(()->{short[] pcm=new short[320];try{while(running){int count=source.read(pcm,0,pcm.length,AudioRecord.READ_BLOCKING);if(count<=0){if(running)failed.run();break;}float[] samples=new float[count];for(int i=0;i<count;i++)samples[i]=pcm[i]/32768f;try{frames.accept(samples);}finally{Arrays.fill(samples,0);Arrays.fill(pcm,(short)0);}}}catch(RuntimeException e){if(running)failed.run();}finally{Arrays.fill(pcm,(short)0);}},"chat-call-capture").start();
        }
        @Override public synchronized void close(){running=false;AudioRecord source=recorder;recorder=null;if(source!=null){try{source.stop();}catch(RuntimeException ignored){}finally{source.release();}}}
    }
    static JSONObject object(Object... pairs){JSONObject result=new JSONObject();for(int i=0;i<pairs.length;i+=2)put(result,(String)pairs[i],pairs[i+1]);return result;}
    private static void put(JSONObject object,String name,Object value){try{object.put(name,value);}catch(JSONException impossible){throw new IllegalArgumentException(impossible);}}
}
