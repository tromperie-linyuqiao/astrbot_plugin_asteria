package com.asteria.chat;

import android.app.NotificationChannel;
import android.app.NotificationManager;

/** The existing reply channel remains authoritative; new categories inherit its choices once. */
final class NotificationChannels {
    static final String REPLY = "texas-chat-replies";
    static final String PROACTIVE = "texas-chat-proactive";
    static final String REMINDER = "texas-chat-reminders";
    static String id(String kind) {
        if ("proactive".equals(kind)) return PROACTIVE;
        if ("reminder".equals(kind)) return REMINDER;
        return REPLY;
    }
    static boolean validKind(String kind) {
        return "reply".equals(kind) || "proactive".equals(kind) || "reminder".equals(kind);
    }
    static boolean isMessageChannel(String id) {
        return REPLY.equals(id) || PROACTIVE.equals(id) || REMINDER.equals(id);
    }
    static void ensure(NotificationManager manager) {
        if (manager == null) return;
        NotificationChannel original = manager.getNotificationChannel(REPLY);
        if (original == null) {
            original = new NotificationChannel(REPLY, "聊天回复", NotificationManager.IMPORTANCE_HIGH);
            original.setDescription("聊天回复提醒；由本机收件产生，非服务器推送。");
            manager.createNotificationChannel(original);
            original = manager.getNotificationChannel(REPLY);
        }
        if (original == null) return;
        inherit(manager, original, PROACTIVE, "主动消息");
        inherit(manager, original, REMINDER, "日程提醒");
    }
    private static void inherit(NotificationManager manager, NotificationChannel original, String id, String name) {
        if (manager.getNotificationChannel(id) != null) return;
        NotificationChannel channel = new NotificationChannel(id, name, original.getImportance());
        channel.setDescription("可单独设置声音、振动和横幅；首次沿用已有聊天回复渠道的设置。");
        channel.setSound(original.getSound(), original.getAudioAttributes());
        channel.setVibrationPattern(original.getVibrationPattern());
        channel.enableVibration(original.shouldVibrate());
        channel.enableLights(original.shouldShowLights());
        channel.setLightColor(original.getLightColor());
        channel.setShowBadge(original.canShowBadge());
        channel.setLockscreenVisibility(original.getLockscreenVisibility());
        if (original.getGroup() != null) channel.setGroup(original.getGroup());
        manager.createNotificationChannel(channel);
    }
    static boolean allowed(NotificationManager manager, String kind) {
        if (manager == null) return false;
        NotificationChannel channel = manager.getNotificationChannel(id(kind));
        return channel != null && channel.getImportance() != NotificationManager.IMPORTANCE_NONE;
    }
    static boolean anyEnabled(NotificationManager manager) {
        return allowed(manager, "reply") || allowed(manager, "proactive") || allowed(manager, "reminder");
    }
}
