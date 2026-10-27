package com.asteria.chat;

import android.app.AppOpsManager;
import android.app.KeyguardManager;
import android.app.usage.UsageEvents;
import android.app.usage.UsageStatsManager;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import android.media.AudioDeviceInfo;
import android.media.AudioManager;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.os.BatteryManager;
import android.os.Build;
import android.os.PowerManager;
import android.os.Process;
import java.util.Locale;
import org.json.JSONObject;

/** User-selected observations only. Missing access omits a section; it never invents a fact. */
public final class PhonePerceptionCollector {
    private static final long APP_WINDOW_MS = 45 * 60 * 1000L;
    private static final String[] PRIVATE_WORDS = {
        "银行", "网银", "支付", "支付宝", "银联", "钱包", "密码", "认证器", "验证器", "口令", "令牌",
        "bank", "alipay", "unionpay", "wallet", "password", "authenticator", "bitwarden", "1password", "keepass"
    };

    private PhonePerceptionCollector() { }

    public static JSONObject build(Context context, boolean basic, boolean app, boolean music) {
        JSONObject frame = new JSONObject();
        put(frame, "ts", System.currentTimeMillis() / 1000.0);
        if (basic) {
            put(frame, "battery", battery(context));
            put(frame, "screen", screen(context));
            put(frame, "network", network(context));
            put(frame, "audio", audio(context));
            put(frame, "device", device(context));
        }
        if (app) put(frame, "app", foreground(context));
        if (music && PerceptionMediaListener.permissionGranted(context)) {
            PerceptionMediaListener.refresh(context);
            put(frame, "music", PerceptionMediaListener.snapshot(context));
        }
        return frame;
    }

    private static JSONObject battery(Context context) {
        try {
            Intent value = context.registerReceiver(null, new IntentFilter(Intent.ACTION_BATTERY_CHANGED));
            if (value == null) return null;
            JSONObject out = new JSONObject();
            int level = value.getIntExtra(BatteryManager.EXTRA_LEVEL, -1);
            int scale = value.getIntExtra(BatteryManager.EXTRA_SCALE, -1);
            if (level >= 0 && scale > 0 && level <= scale) out.put("level", (level * 100) / scale);
            int status = value.getIntExtra(BatteryManager.EXTRA_STATUS, -1);
            int plugged = value.getIntExtra(BatteryManager.EXTRA_PLUGGED, -1);
            if (plugged >= 0 || status == BatteryManager.BATTERY_STATUS_CHARGING || status == BatteryManager.BATTERY_STATUS_FULL
                    || status == BatteryManager.BATTERY_STATUS_DISCHARGING || status == BatteryManager.BATTERY_STATUS_NOT_CHARGING)
                out.put("charging", status == BatteryManager.BATTERY_STATUS_CHARGING
                    || status == BatteryManager.BATTERY_STATUS_FULL || plugged > 0);
            if (plugged >= 0) {
                String type = plugged == 0 ? "none" : (plugged & BatteryManager.BATTERY_PLUGGED_AC) != 0 ? "ac"
                        : (plugged & BatteryManager.BATTERY_PLUGGED_WIRELESS) != 0 ? "wireless"
                        : (plugged & BatteryManager.BATTERY_PLUGGED_USB) != 0 ? "usb" : null;
                if (type != null) out.put("charging_type", type);
            }
            int temperature = value.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, Integer.MIN_VALUE);
            if (temperature >= -400 && temperature <= 1000) out.put("temperature_c", temperature / 10.0);
            return out.length() == 0 ? null : out;
        } catch (Exception unavailable) { return null; }
    }

    private static JSONObject screen(Context context) {
        try {
            PowerManager power = (PowerManager) context.getSystemService(Context.POWER_SERVICE);
            KeyguardManager keyguard = (KeyguardManager) context.getSystemService(Context.KEYGUARD_SERVICE);
            JSONObject out = new JSONObject();
            if (power != null) out.put("on", power.isInteractive());
            if (keyguard != null) out.put("locked", keyguard.isKeyguardLocked());
            return out.length() == 0 ? null : out;
        } catch (Exception unavailable) { return null; }
    }

    private static JSONObject network(Context context) {
        try {
            if (context.checkSelfPermission("android.permission.ACCESS_NETWORK_STATE") != PackageManager.PERMISSION_GRANTED) return null;
            ConnectivityManager manager = (ConnectivityManager) context.getSystemService(Context.CONNECTIVITY_SERVICE);
            if (manager == null) return null;
            Network active = manager.getActiveNetwork();
            if (active == null) return new JSONObject().put("type", "none");
            NetworkCapabilities capabilities = manager.getNetworkCapabilities(active);
            if (capabilities == null) return null;
            String type = capabilities.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) ? "wifi"
                    : capabilities.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) ? "cellular"
                    : capabilities.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) ? "ethernet" : null;
            JSONObject out = new JSONObject().put("metered", !capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_METERED));
            if (type != null) out.put("type", type);
            return out;
        } catch (Exception unavailable) { return null; }
    }

    private static JSONObject audio(Context context) {
        try {
            AudioManager manager = (AudioManager) context.getSystemService(Context.AUDIO_SERVICE);
            if (manager == null) return null;
            JSONObject out = new JSONObject().put("media_active", manager.isMusicActive());
            int mode = manager.getRingerMode();
            if (mode == AudioManager.RINGER_MODE_SILENT) out.put("ringer_mode", "silent");
            else if (mode == AudioManager.RINGER_MODE_VIBRATE) out.put("ringer_mode", "vibrate");
            else if (mode == AudioManager.RINGER_MODE_NORMAL) out.put("ringer_mode", "normal");
            AudioDeviceInfo[] devices = manager.getDevices(AudioManager.GET_DEVICES_OUTPUTS);
            if (devices != null) {
                boolean headphones = false;
                for (AudioDeviceInfo device : devices) {
                    int type = device.getType();
                    if (type == AudioDeviceInfo.TYPE_BLUETOOTH_A2DP || type == AudioDeviceInfo.TYPE_BLUETOOTH_SCO
                            || type == AudioDeviceInfo.TYPE_WIRED_HEADPHONES || type == AudioDeviceInfo.TYPE_WIRED_HEADSET
                            || type == AudioDeviceInfo.TYPE_USB_HEADSET || type == AudioDeviceInfo.TYPE_BLE_HEADSET)
                        headphones = true;
                }
                out.put("headphones", headphones);
            }
            return out;
        } catch (Exception unavailable) { return null; }
    }

    private static JSONObject device(Context context) {
        try {
            JSONObject out = new JSONObject().put("platform", "android");
            String model = text(Build.MODEL, 80), release = text(Build.VERSION.RELEASE, 32);
            if (!model.isEmpty()) out.put("name", model);
            if (!release.isEmpty()) out.put("os_version", release);
            PowerManager power = (PowerManager) context.getSystemService(Context.POWER_SERVICE);
            if (power != null) out.put("power_save", power.isPowerSaveMode());
            return out;
        } catch (Exception unavailable) { return null; }
    }

    public static boolean usagePermissionGranted(Context context) {
        try {
            AppOpsManager manager = (AppOpsManager) context.getSystemService(Context.APP_OPS_SERVICE);
            if (manager == null) return false;
            int mode = Build.VERSION.SDK_INT >= 29
                    ? manager.unsafeCheckOpNoThrow(AppOpsManager.OPSTR_GET_USAGE_STATS, Process.myUid(), context.getPackageName())
                    : manager.checkOpNoThrow(AppOpsManager.OPSTR_GET_USAGE_STATS, Process.myUid(), context.getPackageName());
            return mode == AppOpsManager.MODE_ALLOWED;
        } catch (Exception unavailable) { return false; }
    }

    private static JSONObject foreground(Context context) {
        if (!usagePermissionGranted(context)) return null;
        try {
            PowerManager power = (PowerManager) context.getSystemService(Context.POWER_SERVICE);
            if (power != null && !power.isInteractive()) return null;
            UsageStatsManager manager = (UsageStatsManager) context.getSystemService(Context.USAGE_STATS_SERVICE);
            if (manager == null) return null;
            long now = System.currentTimeMillis(), since = now - APP_WINDOW_MS;
            UsageEvents events = manager.queryEvents(since, now);
            if (events == null) return null;
            UsageEvents.Event event = new UsageEvents.Event();
            String selected = null;
            long entered = 0;
            int count = 0;
            while (events.hasNextEvent()) {
                if (++count > 4096) return null;
                events.getNextEvent(event);
                long at = event.getTimeStamp();
                if (at < since || at > now) continue;
                if (event.getEventType() == UsageEvents.Event.MOVE_TO_FOREGROUND && at >= entered) {
                    selected = event.getPackageName(); entered = at;
                } else if (event.getEventType() == UsageEvents.Event.MOVE_TO_BACKGROUND
                        && selected != null && selected.equals(event.getPackageName()) && at >= entered) {
                    selected = null;
                }
            }
            if (!validPackage(selected) || entered <= 0) return null;
            String label = "";
            try {
                PackageManager packages = context.getPackageManager();
                ApplicationInfo info = packages.getApplicationInfo(selected, 0);
                CharSequence actualLabel = packages.getApplicationLabel(info);
                label = actualLabel == null ? "" : text(actualLabel.toString(), 100);
            } catch (Exception notVisible) { /* Package visibility may withhold the optional label. */ }
            JSONObject out = appObservation(selected, label, entered, now);
            return usagePermissionGranted(context) ? out : null;
        } catch (Exception unavailable) { return null; }
    }

    static boolean validPackage(String value) {
        return value != null && value.length() <= 120 && value.matches("[A-Za-z0-9_]+(?:\\.[A-Za-z0-9_]+)+");
    }

    static JSONObject appObservation(String packageName, String label, long entered, long now) throws Exception {
        if (!validPackage(packageName) || entered <= 0 || now < entered) return null;
        // Apply the privacy check before shortening the optional display label.
        if (sensitive(packageName, label))
            return new JSONObject().put("foreground_package", "private.app").put("foreground_label", "私密应用");
        JSONObject out = new JSONObject().put("foreground_package", packageName)
                .put("foreground_since_epoch", entered / 1000.0)
                .put("foreground_minutes", Math.max(0, (now - entered) / 60000L));
        String boundedLabel = text(label, 60);
        if (!boundedLabel.isEmpty()) out.put("foreground_label", boundedLabel);
        return out;
    }

    static boolean sensitive(String packageName, String label) {
        String value = (packageName + " " + label).toLowerCase(Locale.ROOT);
        for (String word : PRIVATE_WORDS) if (value.contains(word)) return true;
        return false;
    }

    private static String text(String value, int maximum) {
        if (value == null) return "";
        String cleaned = value.replaceAll("[\\p{Cntrl}<>]", " ").trim();
        return cleaned.length() > maximum ? cleaned.substring(0, maximum) : cleaned;
    }

    private static void put(JSONObject target, String key, Object value) {
        if (value == null) return;
        try { target.put(key, value); } catch (Exception unavailable) { }
    }
}
