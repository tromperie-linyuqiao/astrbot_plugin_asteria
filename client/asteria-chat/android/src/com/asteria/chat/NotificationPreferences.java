package com.asteria.chat;

import android.content.Context;
import android.content.SharedPreferences;
import java.util.Calendar;
import org.json.JSONObject;

/** Local delivery choices. These neither grant permission nor start a watcher. */
final class NotificationPreferences {
    final boolean enabled, reply, proactive, reminder, preview, quietEnabled;
    final String quietStart, quietEnd, clickTarget;

    NotificationPreferences(JSONObject value) {
        enabled = bool(value, "enabled", true); reply = bool(value, "reply", true);
        proactive = bool(value, "proactive", true); reminder = bool(value, "reminder", true);
        preview = bool(value, "preview", true); quietEnabled = bool(value, "quiet_enabled", false);
        quietStart = value.optString("quiet_start", "22:00"); quietEnd = value.optString("quiet_end", "08:00");
        minute(quietStart); minute(quietEnd);
        clickTarget = value.optString("click_target", "message");
        if (!("message".equals(clickTarget) || "conversation".equals(clickTarget))) throw new IllegalArgumentException("invalid_click_target");
    }
    private static boolean bool(JSONObject value, String key, boolean fallback) {
        if (!value.has(key)) return fallback;
        if (!(value.opt(key) instanceof Boolean)) throw new IllegalArgumentException("invalid_notification_preference");
        return value.optBoolean(key);
    }
    static int minute(String value) {
        if (value == null || !value.matches("(?:[01][0-9]|2[0-3]):[0-5][0-9]")) throw new IllegalArgumentException("invalid_quiet_time");
        return Integer.parseInt(value.substring(0, 2)) * 60 + Integer.parseInt(value.substring(3));
    }
    static boolean inQuietWindow(int now, int start, int end) {
        return start == end || (start < end ? now >= start && now < end : now >= start || now < end);
    }
    boolean allows(String kind, Calendar now) {
        boolean category = "proactive".equals(kind) ? proactive : "reminder".equals(kind) ? reminder : reply;
        return enabled && category && !(quietEnabled && inQuietWindow(now.get(Calendar.HOUR_OF_DAY) * 60
                + now.get(Calendar.MINUTE), minute(quietStart), minute(quietEnd)));
    }
    JSONObject json() {
        try { return new JSONObject().put("ok", true).put("enabled", enabled).put("reply", reply)
                .put("proactive", proactive).put("reminder", reminder).put("preview", preview)
                .put("quiet_enabled", quietEnabled).put("quiet_start", quietStart).put("quiet_end", quietEnd)
                .put("click_target", clickTarget); }
        catch (Exception impossible) { throw new IllegalStateException(impossible); }
    }
    static NotificationPreferences load(Context context) {
        try { return new NotificationPreferences(new JSONObject(prefs(context).getString("choices", "{}"))); }
        catch (Exception invalid) { return new NotificationPreferences(new JSONObject()); }
    }
    static NotificationPreferences save(Context context, String input) throws Exception {
        if (input == null || input.length() > 4096) throw new IllegalArgumentException("invalid_preferences");
        NotificationPreferences value = new NotificationPreferences(new JSONObject(input));
        if (!prefs(context).edit().putString("choices", value.json().toString()).commit()) throw new IllegalStateException("preferences_not_saved");
        return value;
    }
    private static SharedPreferences prefs(Context context) { return context.getSharedPreferences("asteria_chat_notifications", Context.MODE_PRIVATE); }
}
