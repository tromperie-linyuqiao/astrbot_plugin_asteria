package com.asteria.chat;

import android.content.Context;
import android.content.SharedPreferences;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.util.Base64;
import org.json.JSONObject;

/** Small locally selected portraits, isolated by the existing notification auth scope. */
final class NotificationIdentity {
    final String name, avatar;
    private NotificationIdentity(String name, String avatar) { this.name = name; this.avatar = avatar; }
    private static SharedPreferences prefs(Context context) { return context.getSharedPreferences("asteria_chat_notification_identity", Context.MODE_PRIVATE); }
    static void save(Context context, String scope, String name, String avatar) throws Exception {
        if (name == null || name.trim().isEmpty() || name.length() > 80) throw new IllegalArgumentException("invalid_character_name");
        String clean = name.trim().replace('\n', ' ').replace('\r', ' ');
        if (avatar == null) avatar = "";
        if (!avatar.isEmpty() && bitmap(avatar) == null) throw new IllegalArgumentException("invalid_avatar");
        SharedPreferences values = prefs(context);
        SharedPreferences.Editor edit = values.edit();
        if (!values.contains(scope) && values.getAll().size() >= 16) {
            String oldest = null; long time = Long.MAX_VALUE;
            for (String key : values.getAll().keySet()) {
                try { long saved = new JSONObject(values.getString(key, "{}")).optLong("at"); if (saved < time) { time = saved; oldest = key; } }
                catch (Exception invalid) { oldest = key; break; }
            }
            if (oldest != null) edit.remove(oldest);
        }
        if (!edit.putString(scope, new JSONObject().put("name", clean).put("avatar", avatar).put("at", System.currentTimeMillis()).toString()).commit())
            throw new IllegalStateException("identity_not_saved");
    }
    static NotificationIdentity load(Context context, String scope, String fallback) {
        try { JSONObject row = new JSONObject(prefs(context).getString(scope, "{}"));
            return new NotificationIdentity(row.optString("name", fallback), row.optString("avatar", "")); }
        catch (Exception missing) { return new NotificationIdentity(fallback, ""); }
    }
    static void clear(Context context) { prefs(context).edit().clear().apply(); }
    Bitmap portrait() { return bitmap(avatar); }
    private static Bitmap bitmap(String value) {
        try {
            if (value == null || value.length() > 700000 || !value.matches("data:image/(?:jpeg|png|webp);base64,[A-Za-z0-9+/=]+")) return null;
            int split = value.indexOf(','); byte[] raw = Base64.decode(value.substring(split + 1), Base64.NO_WRAP);
            if (raw.length > 512 * 1024) return null;
            if (!value.substring(5, value.indexOf(';')).equals(AttachmentPolicy.imageSignature(raw))) return null;
            BitmapFactory.Options bounds = new BitmapFactory.Options(); bounds.inJustDecodeBounds = true;
            BitmapFactory.decodeByteArray(raw, 0, raw.length, bounds);
            if (bounds.outWidth <= 0 || bounds.outHeight <= 0 || bounds.outWidth > 4096 || bounds.outHeight > 4096) return null;
            BitmapFactory.Options size = new BitmapFactory.Options(); size.inSampleSize = 1;
            while (Math.max(bounds.outWidth, bounds.outHeight) / size.inSampleSize > 256) size.inSampleSize *= 2;
            return BitmapFactory.decodeByteArray(raw, 0, raw.length, size);
        } catch (RuntimeException | OutOfMemoryError invalid) { return null; }
    }
}
