package com.asteria.chat;
import android.content.Context;
import org.json.JSONObject;
import org.json.JSONArray;

/** Only explicit foreground viewport reports may quiet an already-saved ID. */
final class DeviceContinuity {
    static synchronized String id(Context context){
        android.content.SharedPreferences prefs=context.getSharedPreferences("device-continuity",Context.MODE_PRIVATE);
        String value=prefs.getString("device_id","");
        if(value.isEmpty()){value="android-"+java.util.UUID.randomUUID();if(!prefs.edit().putString("device_id",value).commit())throw new IllegalStateException("device_id_save_failed");}
        return value;
    }
    static boolean visibleElsewhere(JSONObject data,String id,String device){
        if(data==null||data.optInt("schema")!=1)return false;
        JSONArray rows=data.optJSONArray("visible");double now=data.optDouble("server_time",0);
        if(rows==null||now<=0)return false;
        for(int i=0;i<rows.length();i++){
            JSONObject row=rows.optJSONObject(i);if(row==null||device.equals(row.optString("device_id")))continue;
            double age=now-row.optDouble("at",0);if(age<0||age>=30)continue;
            JSONArray ids=row.optJSONArray("message_ids");if(ids!=null)for(int j=0;j<ids.length();j++)if(id.equals(ids.optString(j)))return true;
        }
        return false;
    }
}
