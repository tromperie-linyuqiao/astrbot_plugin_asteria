package com.asteria.chat;

import com.k2fsa.sherpa.onnx.*;
import java.io.File;
import java.util.concurrent.Semaphore;
import java.util.concurrent.TimeUnit;

/** Reused offline SenseVoice model. All model ownership stays on one recognition worker. */
final class CallSpeechEngine implements CallSession.Recognizer {
    private final File directory;
    private OfflineRecognizer recognizer;
    private static final Semaphore modelOwner=new Semaphore(1,true);
    private boolean lease;private volatile boolean cancelled;
    CallSpeechEngine(File directory){this.directory=directory;}
    @Override public String recognize(float[] samples) throws Exception {
        while(!lease){if(cancelled)throw new InterruptedException("通话已结束");if(modelOwner.tryAcquire(200,TimeUnit.MILLISECONDS))lease=true;}
        if(cancelled)throw new InterruptedException("通话已结束");
        if(recognizer==null){
            CallModelStore.verify(directory);
            LibraryLoader.setAutoLoadEnabled(false);
            System.loadLibrary("sherpa-onnx-jni");
            OfflineSenseVoiceModelConfig sense=OfflineSenseVoiceModelConfig.builder().setModel(new File(directory,"model.int8.onnx").getPath()).setLanguage("auto").setInverseTextNormalization(true).build();
            OfflineModelConfig model=OfflineModelConfig.builder().setSenseVoice(sense).setTokens(new File(directory,"tokens.txt").getPath()).setNumThreads(2).setProvider("cpu").setDebug(false).build();
            recognizer=new OfflineRecognizer(OfflineRecognizerConfig.builder().setOfflineModelConfig(model).setFeatureConfig(FeatureConfig.builder().setSampleRate(16000).setFeatureDim(80).build()).setDecodingMethod("greedy_search").build());
        }
        OfflineStream stream=recognizer.createStream();
        try{stream.acceptWaveform(samples,16000);recognizer.decode(stream);String text=recognizer.getResult(stream).getText().replaceAll("<\\|[^|>]*\\|>","").trim();if(text.length()>16000)throw new IllegalStateException("识别文字过长，请缩短分句");return text;}
        finally{stream.release();}
    }
    @Override public void cancel(){cancelled=true;}
    @Override public void close(){try{if(recognizer!=null){recognizer.release();recognizer=null;}}finally{if(lease){lease=false;modelOwner.release();}}}
}
