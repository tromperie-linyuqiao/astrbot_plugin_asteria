package com.asteria.chat;

import android.content.Context;
import java.io.*;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.security.MessageDigest;
import java.util.HashSet;
import java.util.Set;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

/** Explicit local ZIP import. The two accepted model files are pinned, not arbitrary executables. */
final class CallModelStore {
    static final long MODEL_BYTES=239233841,TOKEN_BYTES=315894;
    static final String MODEL_SHA="c71f0ce00bec95b07744e116345e33d8cbbe08cef896382cf907bf4b51a2cd51",TOKEN_SHA="f449eb28dc567533d7fa59be34e2abca8784f771850c78a47fb731a31429a1dc";
    static File directory(Context context){return new File(context.getNoBackupFilesDir(),"call-sensevoice");}
    static boolean ready(File directory){return new File(directory,"model.int8.onnx").length()==MODEL_BYTES&&new File(directory,"tokens.txt").length()==TOKEN_BYTES;}
    static String digest(File file)throws Exception {MessageDigest digest=MessageDigest.getInstance("SHA-256");byte[] buffer=new byte[65536];try(InputStream input=new FileInputStream(file)){int n;while((n=input.read(buffer))!=-1)digest.update(buffer,0,n);}StringBuilder text=new StringBuilder();for(byte value:digest.digest())text.append(String.format(java.util.Locale.ROOT,"%02x",value&255));return text.toString();}
    static synchronized void verify(File directory)throws Exception {if(!ready(directory)||!MODEL_SHA.equals(digest(new File(directory,"model.int8.onnx")))||!TOKEN_SHA.equals(digest(new File(directory,"tokens.txt"))))throw new IOException("请先导入完整的离线语音模型");}
    static synchronized void install(File directory,InputStream source)throws Exception {
        if(!directory.isDirectory()&&!directory.mkdirs())throw new IOException("无法创建模型目录");
        File model=new File(directory,"model.import"),tokens=new File(directory,"tokens.import");Set<String> found=new HashSet<>();
        try(ZipInputStream zip=new ZipInputStream(source)){
            int entries=0;ZipEntry entry;byte[] buffer=new byte[65536];
            while((entry=zip.getNextEntry())!=null){
                if(++entries>8||entry.isDirectory())throw new IOException("模型压缩包结构不正确");
                String name=entry.getName();File target;long expected;
                if(name.equals("model.int8.onnx")){target=model;expected=MODEL_BYTES;}
                else if(name.equals("tokens.txt")){target=tokens;expected=TOKEN_BYTES;}
                else if(name.equals("LICENSE")||name.equals("MODEL_LICENSE.txt")||name.equals("README.md")){long count=0;int n;while((n=zip.read(buffer))!=-1){count+=n;if(count>65536)throw new IOException("说明文件过大");}continue;}
                else throw new IOException("请选择提供的 SenseVoice 离线模型 ZIP");
                if(!found.add(name))throw new IOException("模型文件重复");
                long count=0;try(OutputStream output=new FileOutputStream(target)){int n;while((n=zip.read(buffer))!=-1){count+=n;if(count>expected)throw new IOException("模型大小不正确");output.write(buffer,0,n);}}
                if(count!=expected)throw new IOException("模型不完整");
            }
            if(found.size()!=2||!MODEL_SHA.equals(digest(model))||!TOKEN_SHA.equals(digest(tokens)))throw new IOException("模型校验失败，未启用");
            Files.move(model.toPath(),new File(directory,"model.int8.onnx").toPath(),StandardCopyOption.REPLACE_EXISTING,StandardCopyOption.ATOMIC_MOVE);
            Files.move(tokens.toPath(),new File(directory,"tokens.txt").toPath(),StandardCopyOption.REPLACE_EXISTING,StandardCopyOption.ATOMIC_MOVE);
        }finally{Files.deleteIfExists(model.toPath());Files.deleteIfExists(tokens.toPath());}
    }
}
