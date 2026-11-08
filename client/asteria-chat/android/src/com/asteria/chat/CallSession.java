package com.asteria.chat;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.function.BooleanSupplier;

/** No sender: finalized turns are acknowledged only by the existing WebView chat pipeline. */
final class CallSession implements AutoCloseable {
    interface Frames {void accept(float[] samples);}
    interface Capture extends AutoCloseable {void start(Frames frames,Runnable failed)throws Exception;void close();}
    interface Factory {Capture create();}
    interface Recognizer extends AutoCloseable {String recognize(float[] samples)throws Exception;default void cancel(){}void close();}
    interface Listener {void changed(Snapshot value);}
    static final class Turn {final int sequence;final String text;Turn(int sequence,String text){this.sequence=sequence;this.text=text;}}
    static final class Snapshot {
        final boolean active,muted,held,capturing,output;final String message;final double level;final List<Turn> turns;
        Snapshot(boolean active,boolean muted,boolean held,boolean capturing,boolean output,String message,double level,List<Turn> turns){this.active=active;this.muted=muted;this.held=held;this.capturing=capturing;this.output=output;this.message=message;this.level=level;this.turns=turns;}
    }
    private static final class Clip {final int epoch;final float[] samples;Clip(int epoch,float[] samples){this.epoch=epoch;this.samples=samples;}}
    private final Object lock=new Object();
    private final ArrayDeque<Clip> clips=new ArrayDeque<>();
    private final LinkedHashMap<Integer,Turn> turns=new LinkedHashMap<>();
    private final CallSegmenter segmenter;
    private final BooleanSupplier current;private final Factory factory;private final Recognizer recognizer;private final Listener listener;
    private Capture capture;private Thread worker;private int epoch,sequence;
    private boolean active,muted,held,output,capturing;private String message="通话未开始";private double level;private long lastLevel;
    CallSession(BooleanSupplier current,Factory factory,Recognizer recognizer,Listener listener,int silence,float threshold){this.current=current;this.factory=factory;this.recognizer=recognizer;this.listener=listener;segmenter=new CallSegmenter(silence,threshold);}
    void start()throws Exception {
        if(!current.getAsBoolean())throw new IllegalStateException("会话已变化");
        synchronized(lock){if(worker!=null)throw new IllegalStateException("请重新打开电话模式");active=true;message="正在听你说 · 停顿后自动发送";worker=new Thread(this::work,"chat-call-asr");worker.start();}
        try{openCapture();}catch(Exception e){close();throw e;}
    }
    private void openCapture()throws Exception {
        if(!current.getAsBoolean()){close();return;}
        final int ticket;final Capture source;
        synchronized(lock){if(!active||muted||held||output||capture!=null)return;source=factory.create();capture=source;capturing=true;ticket=epoch;message="正在听你说 · 停顿后自动发送";}
        try{source.start(samples->frames(ticket,samples),()->pause("麦克风已中断，请检查后明确继续"));}
        catch(Exception e){stopCapture();throw e;}
        emit();
    }
    private void frames(int ticket,float[] samples){
        if(!current.getAsBoolean()){close();return;}
        boolean full=false,notify=false;
        try{synchronized(lock){
            if(!active||!capturing||ticket!=epoch)return;
            for(float[] clip:segmenter.push(samples)){
                if(clips.size()<4)clips.add(new Clip(ticket,clip));else{Arrays.fill(clip,0);full=true;}
                if(clips.size()>=4){held=true;capturing=false;full=true;}
            }
            lock.notifyAll();level=segmenter.level;long now=System.nanoTime();if(now-lastLevel>=250000000){lastLevel=now;notify=true;}
        }}catch(Exception e){pause("麦克风数据异常，请检查后明确继续");return;}
        if(full){stopCapture();synchronized(lock){message="识别排队较多，已暂停收音；处理后可点继续";}emit();}
        else if(notify)emit();
    }
    private void work(){
        try{while(true){
            if(!current.getAsBoolean()){close();break;}
            Clip clip;
            synchronized(lock){if(!active)break;if(clips.isEmpty()||turns.size()>=16){try{lock.wait(250);}catch(InterruptedException e){Thread.currentThread().interrupt();break;}continue;}clip=clips.remove();}
            try{
                synchronized(lock){if(!active||clip.epoch!=epoch)continue;message="本机正在转文字";}
                emit();String text=recognizer.recognize(clip.samples);
                if(!current.getAsBoolean()){close();break;}
                boolean full=false;
                synchronized(lock){if(active&&!muted&&clip.epoch==epoch&&text!=null&&!text.trim().isEmpty()){if(text.length()>16000)throw new IllegalStateException("识别文字过长");Turn turn=new Turn(++sequence,text.trim());turns.put(turn.sequence,turn);if(turns.size()>=16){held=true;full=true;}message=full?"待发送片段较多，已暂停收音；请先处理聊天":"已转文字 · 等待聊天确认";}}
                if(full)stopCapture();emit();
            }catch(Throwable e){if(e instanceof ThreadDeath)throw (ThreadDeath)e;pause("离线识别未完成，请检查模型或设备后明确继续");}
            finally{Arrays.fill(clip.samples,0);}
        }}finally{recognizer.close();}
    }
    void ack(int sequence){synchronized(lock){turns.remove(sequence);lock.notifyAll();}emit();}
    void mute(){synchronized(lock){if(!active)return;epoch++;muted=true;clearClips();message="已静音 · 麦克风已关闭";}stopCapture();emit();}
    void pause(String why){mute();synchronized(lock){message=why;}emit();}
    void resume()throws Exception {if(!current.getAsBoolean()){close();return;}synchronized(lock){if(!active)throw new IllegalStateException("通话已结束");if(clips.size()>=3||turns.size()>=16)throw new IllegalStateException("请先处理当前聊天，再继续");muted=held=false;}openCapture();}
    void output(boolean value)throws Exception {synchronized(lock){output=value;if(value)message="正在播放声音，暂停收音以避免回声";}if(value)stopCapture();else openCapture();emit();}
    Snapshot snapshot(){synchronized(lock){return new Snapshot(active,muted,held,capturing,output,message,level,new ArrayList<>(turns.values()));}}
    private void clearClips(){while(!clips.isEmpty())Arrays.fill(clips.remove().samples,0);segmenter.clear();level=0;}
    private void stopCapture(){Capture old;synchronized(lock){capturing=false;segmenter.clear();level=0;old=capture;capture=null;}if(old!=null)try{old.close();}catch(RuntimeException ignored){/* state is already stopped, never reopen automatically */}}
    private void emit(){listener.changed(snapshot());}
    @Override public void close(){synchronized(lock){active=false;epoch++;muted=held=false;clearClips();turns.clear();message="通话已结束 · 麦克风已关闭";lock.notifyAll();}recognizer.cancel();stopCapture();emit();}
}
