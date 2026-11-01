package com.asteria.chat;

import android.app.Activity;
import android.media.AudioAttributes;
import android.media.MediaPlayer;
import android.media.AudioManager;
import android.media.AudioFocusRequest;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.speech.tts.TextToSpeech;
import android.speech.tts.UtteranceProgressListener;
import android.speech.tts.Voice;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.Locale;
import org.json.JSONArray;
import org.json.JSONObject;

/** Device-engine speech, deliberately independent from chat generation and delivery. */
final class AsteriaVoice {
    interface Reply { void done(JSONObject result); }
    interface Observer { void changed(JSONObject state); }
    private final Activity activity;
    private final Observer observer;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private TextToSpeech tts;
    private MediaPlayer player;
    private AudioManager audioManager;
    private AudioFocusRequest focus;
    private boolean ready, initialized, closed;
    private String phase = "idle", utterance = "", message = "", voiceId = "";
    private String requestId = "";
    private boolean network;
    private File pending;
    private final ArrayList<Runnable> waiting = new ArrayList<>();
    private int sequence;
    private final Runnable ticker = new Runnable() { public void run() {
        if (closed || !"playing".equals(phase)) return;
        publish(""); handler.postDelayed(this, 500);
    }};
    private final Runnable synthesisTimeout = () -> { if ("synthesizing".equals(phase)) fail("系统朗读等待超时，请稍后手动重试。"); };
    AsteriaVoice(Activity activity, Observer observer) { this.activity = activity; this.observer = observer; }
    private static JSONObject json(Object... items) {
        JSONObject value = new JSONObject();
        try { for (int i=0;i<items.length;i+=2) value.put((String)items[i],items[i+1]); } catch(Exception ignored) { }
        return value;
    }
    private void initialize(Runnable next) {
        if (closed) return;
        if (initialized) { next.run(); return; }
        if (waiting.size() >= 8) return;
        waiting.add(next);
        if (tts != null) return;
        tts = new TextToSpeech(activity, code -> handler.post(() -> {
            if (closed) return;
            initialized = true; ready = code == TextToSpeech.SUCCESS;
            if (ready) tts.setOnUtteranceProgressListener(new UtteranceProgressListener() {
                @Override public void onStart(String id) { }
                @Override public void onDone(String id) { handler.post(() -> {
                    if (!closed && id.equals(utterance) && pending != null) {
                        handler.removeCallbacks(synthesisTimeout);
                        if (pending.length() == 0) fail("系统音色未生成可播放音频。");
                        else { File file=pending; pending=null; play(file); }
                    }
                }); }
                @Override public void onError(String id) { handler.post(() -> { if(id.equals(utterance)) fail("系统音色合成失败，请检查语音数据或网络。"); }); }
            });
            ArrayList<Runnable> jobs = new ArrayList<>(waiting); waiting.clear();
            for (Runnable job : jobs) job.run();
        }));
    }
    void command(JSONObject input, String accountScope, Reply reply) {
        if (closed) { reply.done(json("ok",false,"message","语音窗口已关闭")); return; }
        String action=input.optString("action");
        if ("status".equals(action)) { reply.done(status("")); return; }
        if ("stop".equals(action)) { stop(); reply.done(status("")); return; }
        if ("pause".equals(action)) { if(player!=null && "playing".equals(phase)){player.pause();phase="paused";handler.removeCallbacks(ticker);releaseFocus();}publish("");reply.done(status(""));return; }
        if ("resume".equals(action)) { if(player!=null && "paused".equals(phase)){if(!acquireFocus()){reply.done(json("ok",false,"message","其他应用正在使用音频"));return;}player.start();phase="playing";handler.post(ticker);}reply.done(status(""));return; }
        if ("clear".equals(action)) { stop(); File[] files=directory().listFiles();if(files!=null)for(File file:files)if(file.getName().matches("[a-f0-9]{64}\\.wav"))file.delete();reply.done(status("本机语音副本已清理，聊天历史不变。"));return; }
        if (!"voices".equals(action) && !"speak".equals(action)) {reply.done(json("ok",false,"message","未知语音操作"));return;}
        final int ticket=sequence;
        initialize(() -> {
            if (closed || ticket!=sequence) {reply.done(json("ok",false,"message","语音请求已取消"));return;}
            if (!ready) {reply.done(json("ok",false,"message","设备没有可用的系统语音引擎，请先在 Android 文字转语音设置中安装中文音色。"));return;}
            try {
                if("voices".equals(action)) {
                    JSONArray voices=new JSONArray();
                    if(tts.getVoices()!=null) for(Voice voice:tts.getVoices()) voices.put(json("id",voice.getName(),"language",voice.getLocale().toLanguageTag(),"network",voice.isNetworkConnectionRequired(),"quality",voice.getQuality()));
                    reply.done(json("ok",true,"voices",voices,"max_characters",Math.min(3500,TextToSpeech.getMaxSpeechInputLength()-1),"engine",tts.getDefaultEngine()));return;
                }
                String text=input.optString("text"), id=input.optString("message_id");
                if(text.trim().isEmpty() || text.length()>=TextToSpeech.getMaxSpeechInputLength() || text.length()>3500 || id.length()>200 || id.isEmpty()) throw new IllegalArgumentException("单次朗读支持 1–3500 字，请选择较短的消息或试听文本。");
                double rate=input.optDouble("rate",0.95), pitch=input.optDouble("pitch",1.0);
                if(!Double.isFinite(rate)||!Double.isFinite(pitch)||rate<0.7||rate>1.3||pitch<0.8||pitch>1.2)throw new IllegalArgumentException("语音参数无效");
                String desired=input.optString("voice_id"), language=input.optString("language","zh-CN");
                Voice chosen=null;
                if(tts.getVoices()!=null)for(Voice voice:tts.getVoices())if(voice.getName().equals(desired))chosen=voice;
                if(!desired.isEmpty() && chosen==null) throw new IllegalArgumentException("保存的音色在本机不可用，请重新选择设备音色。");
                if(chosen!=null){if(tts.setVoice(chosen)!=TextToSpeech.SUCCESS)throw new IllegalArgumentException("设备无法使用这个音色");}
                else if(tts.setLanguage(Locale.forLanguageTag(language))<TextToSpeech.LANG_AVAILABLE)throw new IllegalArgumentException("设备未安装所选语言的语音数据");
                stop(); message=id;requestId=input.optString("request_id");Voice actual=tts.getVoice();voiceId=actual==null?"":actual.getName();network=actual!=null&&actual.isNetworkConnectionRequired();
                tts.setSpeechRate((float)rate);tts.setPitch((float)pitch);
                File target=new File(directory(),digest(accountScope+"\n"+id+"\n"+voiceId+"\n"+language+rate+":"+pitch+"\n"+text)+".wav");
                if(target.isFile() && target.length()>0){target.setLastModified(System.currentTimeMillis());play(target);reply.done(status(""));return;}
                trimCache();utterance="texas-voice-"+(++sequence);pending=target;phase="synthesizing";publish("");
                Bundle params=new Bundle();params.putString(TextToSpeech.Engine.KEY_PARAM_UTTERANCE_ID,utterance);
                if(tts.synthesizeToFile(text,params,target,utterance)!=TextToSpeech.SUCCESS)throw new IllegalStateException("系统语音合成未能启动");
                handler.postDelayed(synthesisTimeout,60000);reply.done(status(""));
            }catch(Exception failure){fail(failure.getMessage()==null?"语音暂不可用":failure.getMessage());reply.done(json("ok",false,"message",failure.getMessage()));}
        });
    }
    int beginRemote(String id, String request) {
        stop(); message=id; requestId=request; voiceId="cloud"; network=true;
        phase="preparing"; publish(""); return sequence;
    }
    void remoteReady(int ticket, File file) {if(!closed && ticket==sequence){play(file);}}
    void remoteFailed(int ticket, String error) {if(!closed && ticket==sequence)fail(error);}
    private File directory(){File file=new File(activity.getCacheDir(),"texas-voice");file.mkdirs();return file;}
    private static String digest(String text)throws Exception{byte[] bytes=MessageDigest.getInstance("SHA-256").digest(text.getBytes(StandardCharsets.UTF_8));StringBuilder out=new StringBuilder();for(byte b:bytes)out.append(String.format(Locale.ROOT,"%02x",b&255));return out.toString();}
    private void trimCache(){File[] files=directory().listFiles();if(files==null)return;Arrays.sort(files,Comparator.comparingLong(File::lastModified).reversed());long bytes=0;int count=0;for(File file:files)if(file.getName().endsWith(".wav")){bytes+=file.length();if(++count>16||bytes>24L*1024*1024)file.delete();}}
    private boolean acquireFocus(){
        releaseFocus();
        audioManager=(AudioManager)activity.getSystemService(Activity.AUDIO_SERVICE);
        if(audioManager==null)return false;
        focus=new AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT)
            .setAudioAttributes(new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA).setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
            .setOnAudioFocusChangeListener(change->{if(change<0 && player!=null && "playing".equals(phase)){player.pause();phase="paused";handler.removeCallbacks(ticker);publish("音频焦点已让给其他应用，可手动继续。");}},handler).build();
        return audioManager.requestAudioFocus(focus)==AudioManager.AUDIOFOCUS_REQUEST_GRANTED;
    }
    private void releaseFocus(){if(audioManager!=null&&focus!=null)audioManager.abandonAudioFocusRequest(focus);focus=null;}
    void background(){if("synthesizing".equals(phase)||"preparing".equals(phase))stop();else if(player!=null&&"playing".equals(phase)){player.pause();phase="paused";handler.removeCallbacks(ticker);releaseFocus();publish("");}}
    private void play(File file){
        try{player=new MediaPlayer();player.setAudioAttributes(new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA).setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build());player.setDataSource(file.getAbsolutePath());phase="preparing";publish("");
            player.setOnPreparedListener(value->{if(value!=player||closed)return;if(!acquireFocus()){fail("当前不能取得音频播放权限，请稍后重试。");return;}value.start();phase="playing";handler.post(ticker);});
            player.setOnCompletionListener(value->{if(value!=player)return;phase="completed";releaseFocus();handler.removeCallbacks(ticker);publish("");value.release();player=null;});
            player.setOnErrorListener((value,what,extra)->{if(value==player)fail("音频播放失败，可以重新朗读。");return true;});player.prepareAsync();
        }catch(Exception failure){file.delete();fail("音频无法打开，请重新朗读。");}
    }
    private JSONObject status(String error){int position=0,duration=0;try{if(player!=null&&("playing".equals(phase)||"paused".equals(phase))){position=player.getCurrentPosition();duration=player.getDuration();}}catch(IllegalStateException ignored){}
        return json("ok",true,"phase",phase,"message_id",message,"request_id",requestId,"voice_id",voiceId,"network",network,"position_ms",position,"duration_ms",duration,"message",error);}
    private void publish(String error){if(!closed)observer.changed(status(error));}
    private void fail(String error){stop();phase="error";publish(error);}
    void stop(){releaseFocus();sequence++;utterance="";handler.removeCallbacks(synthesisTimeout);handler.removeCallbacks(ticker);if(tts!=null)tts.stop();if(player!=null){player.release();player=null;}if(pending!=null){pending.delete();pending=null;}phase="stopped";publish("");}
    void close(){stop();closed=true;waiting.clear();if(tts!=null){tts.shutdown();tts=null;}}
}
