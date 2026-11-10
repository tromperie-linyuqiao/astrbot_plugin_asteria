package com.asteria.chat;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

/** Local PCM boundaries only. No network, model, files or word-based deduplication. */
final class CallSegmenter {
    static final int RATE=16000, MAX=20*RATE;
    private final int silence;
    private final float threshold;
    private final float[] speech=new float[MAX],lead=new float[RATE/4];
    private int size,leadSize,leadAt,voiced,quiet;
    double level;
    CallSegmenter(int milliseconds,float threshold) {
        if(milliseconds<400||milliseconds>2500||threshold<.001f||threshold>.1f)throw new IllegalArgumentException("分句设置无效");
        silence=RATE*milliseconds/1000;this.threshold=threshold;
    }
    List<float[]> push(float[] frame) {
        List<float[]> ready=new ArrayList<>();
        for(int offset=0;offset<frame.length;) {
            int count=Math.min(320,frame.length-offset);if(size>0)count=Math.min(count,MAX-size);
            double square=0;
            for(int i=0;i<count;i++){float v=frame[offset+i];if(Float.isNaN(v)||Float.isInfinite(v)||Math.abs(v)>1.001f)throw new IllegalArgumentException("麦克风数据异常");square+=(double)v*v;}
            level=Math.sqrt(square/count);boolean voice=level>=threshold;
            if(size==0&&voice){for(int i=0;i<leadSize;i++)speech[size++]=lead[(leadAt-leadSize+i+lead.length)%lead.length];leadSize=leadAt=0;}
            if(size>0||voice) {
                System.arraycopy(frame,offset,speech,size,count);size+=count;
                if(voice){voiced+=count;quiet=0;}else quiet+=count;
                if(quiet>=silence||size==MAX){if(voiced>=RATE*15/100)ready.add(Arrays.copyOf(speech,size));clear();}
            } else for(int i=0;i<count;i++){lead[leadAt]=frame[offset+i];leadAt=(leadAt+1)%lead.length;leadSize=Math.min(leadSize+1,lead.length);}
            offset+=count;
        }
        return ready;
    }
    float[] finish(){float[] result=voiced>=RATE*15/100?Arrays.copyOf(speech,size):null;clear();return result;}
    void clear(){Arrays.fill(speech,0);Arrays.fill(lead,0);size=leadSize=leadAt=voiced=quiet=0;level=0;}
}
