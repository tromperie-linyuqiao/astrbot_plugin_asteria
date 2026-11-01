package com.asteria.chat;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Person;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.content.pm.ServiceInfo;
import android.content.pm.ShortcutInfo;
import android.content.pm.ShortcutManager;
import android.net.Uri;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.SystemClock;
import android.provider.Settings;
import android.graphics.Bitmap;
import android.graphics.drawable.Icon;
import android.service.notification.StatusBarNotification;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;
import javax.net.ssl.HttpsURLConnection;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/** Explicit bounded foreground-service polling per account. This is not push. */
public final class ReplyWatchService extends Service {
    private static final String START = "com.asteria.chat.REPLY_WATCH_START";
    private static final String STOP = "com.asteria.chat.REPLY_WATCH_STOP";
    private static final String WATCH_CHANNEL = "asteria-chat-reply-watch";
    private static final String REPLY_CHANNEL = "asteria-chat-replies";
    private static final int WATCH_NOTIFICATION = 4300;
    private static final int MAX_NOTICE_MESSAGES = 8;
    private static final String SHORTCUT_PREFIX = "asteria-chat.reply.";
    private static final String NOTICE_PREFIX = "asteria-chat.message.";
    private static final long POLL_MS = 30000;
    private static final Object ADMISSION = new Object();
    private static long admissionEpoch;
    private static boolean startPending;
    private static final int MAX_WATCHES = 6;
    private static volatile String visibleAccount = "";
    private static volatile ReplyWatchService current;
    private static volatile boolean appForeground;
    private static final String EMPTY_STATUS = "{\"state\":\"stopped\",\"running\":false,\"active\":false,\"accounts\":[],\"verified_session\":false,\"server_push\":false,\"transport\":\"foreground_service_polling\"}";
    private static volatile String latest = EMPTY_STATUS;
    private static volatile Observer observer;

    interface Observer { void changed(String state); }

    private final Handler main = new Handler(Looper.getMainLooper());
    private final ScheduledExecutorService executor = Executors.newScheduledThreadPool(2, runnable -> {
        Thread thread = new Thread(runnable, "asteria-chat-reply-watch");
        thread.setDaemon(true);
        return thread;
    });
    private final Map<String, Watch> watches = new ConcurrentHashMap<>();
    private volatile boolean running;
    private SharedPreferences metadata;

    private static final class Watch {
        final String server, token, session, title, scope, baseline;
        ReplyWatchAccounts.Record registration;
        final AtomicBoolean polling = new AtomicBoolean();
        volatile HttpsURLConnection connection;
        volatile ScheduledFuture<?> pending;
        volatile long lastNetworkStarted = -POLL_MS, nextPollAt;
        volatile String state = "starting", reason = "";
        volatile boolean initialized, verified, receiptsSupported, syncSupported, syncBlocked;
        volatile String receiptState = "not_reported";
        volatile String cursor = "";
        volatile String syncCursor = "", syncState = "not_checked";
        volatile long lastSyncAt;
        volatile int uncertainNotices;
        final List<NoticeMessage> notices = new ArrayList<>();
        int failures;
        Watch(String server, String token, String session, String title, String baseline) {
            this.server = server; this.token = token; this.session = session;
            this.title = text(title, BuildConfig.APP_NAME, 40); this.baseline = baseline == null ? "" : baseline;
            scope = scope(server, token, session);
        }
        Watch(ReplyWatchAccounts.Record record) {
            this(record.server, record.token, record.session, record.title, record.baseline);
            registration = record;
        }
    }

    private static final class NoticeMessage {
        final String id, text;
        final long timestamp;
        String kind = "reply", imageFilename = "";
        NoticeMessage(String id, String text, long timestamp) {
            this.id = id; this.text = text; this.timestamp = timestamp;
        }
    }

    static String snapshot() { return latest; }
    static String snapshot(Context context) {
        synchronized (ADMISSION) {
            try { return statusSnapshot(context, null, null).toString(); }
            catch (RuntimeException | JSONException unavailable) { return EMPTY_STATUS; }
        }
    }

    private static JSONObject statusSnapshot(Context context, String state, String reason) throws JSONException {
        ReplyWatchService service = current;
        SharedPreferences saved = context.getSharedPreferences("asteria_chat_reply_watch", MODE_PRIVATE);
        JSONArray accounts = new JSONArray();
        java.util.Set<String> known = new java.util.HashSet<>();
        Watch selected = null;
        int activeCount = 0;
        for (ReplyWatchAccounts.Record record : ReplyWatchAccounts.list(context)) {
            known.add(record.id);
            Watch live = service == null ? null : service.watches.get(record.id);
            if (live != null && !service.current(live)) live = null;
            boolean active = live != null;
            if (active) { activeCount++; if (selected == null || isVisible(live)) selected = live; }
            JSONObject row = new JSONObject().put("id", record.id).put("server", record.server)
                    .put("username", record.username).put("session_id", record.session).put("title", record.title)
                    .put("account_id", record.id).put("can_activate", true).put("registered", true).put("enabled", saved.getBoolean("enabled", false) && !saved.getBoolean("paused_" + record.id, false))
                    .put("active", active).put("running", active).put("verified_session", active && live.verified)
                    .put("state", active ? live.state : "stopped")
                    .put("reason", active ? live.reason : saved.getString("stop_reason_" + record.id, "service_not_running"))
                    .put("foreground_visible", active && isVisible(live))
                    .put("receipt_sync", active ? live.receiptState : "not_reported")
                    .put("message_sync", active ? live.syncState : "not_checked")
                    .put("last_sync_at", active && live.lastSyncAt > 0 ? live.lastSyncAt : JSONObject.NULL)
                    .put("next_poll_seconds", active ? Math.max(0, live.nextPollAt - SystemClock.elapsedRealtime()) / 1000 : 0)
                    .put("notification_outcome_unknown", active ? live.uncertainNotices : 0);
            accounts.put(row);
        }
        JSONArray stopped = stoppedAccounts(saved);
        for (int index = 0; index < stopped.length(); index++) {
            JSONObject row = stopped.optJSONObject(index);
            if (row != null && !known.contains(row.optString("id"))) accounts.put(row);
        }
        return new JSONObject().put("state", state != null ? state : activeCount > 0 ? "running" : "stopped")
                .put("reason", reason == null ? JSONObject.NULL : reason).put("running", activeCount > 0)
                .put("active", activeCount > 0).put("active_count", activeCount).put("registered_count", known.size())
                .put("accounts", accounts).put("maximum_accounts", MAX_WATCHES)
                .put("verified_session", selected != null && selected.verified)
                .put("session_id", selected == null ? JSONObject.NULL : selected.session)
                .put("title", selected == null ? JSONObject.NULL : selected.title)
                .put("poll_interval_seconds", 30).put("next_poll_seconds", selected == null ? 0 : Math.max(0, selected.nextPollAt - SystemClock.elapsedRealtime()) / 1000)
                .put("server_push", false).put("requires_explicit_enable", true)
                .put("transport", "foreground_service_polling").put("process_exit_delivery_guaranteed", false)
                .put("force_stop_delivery_guaranteed", false).put("system_restart_recovery", true)
                .put("system_time_limit_applies", true).put("system_restart_recovery_guaranteed", false)
                .put("receipt_sync", selected == null ? "not_reported" : selected.receiptState)
                .put("message_sync", selected == null ? "not_checked" : selected.syncState)
                .put("last_sync_at", selected == null || selected.lastSyncAt == 0 ? JSONObject.NULL : selected.lastSyncAt)
                .put("notification_outcome_unknown", selected == null ? 0 : selected.uncertainNotices);
    }

    static String notificationStatus(Context context) {
        try {
            NotificationManager manager = context.getSystemService(NotificationManager.class);
            if (manager == null) throw new IllegalStateException("notification_manager_unavailable");
            boolean permission = Build.VERSION.SDK_INT < 33 || context.checkSelfPermission(
                    "android.permission.POST_NOTIFICATIONS") == PackageManager.PERMISSION_GRANTED;
            boolean enabled = manager.areNotificationsEnabled();
            NotificationChannel replies = manager.getNotificationChannel(REPLY_CHANNEL);
            NotificationChannel watchChannel = manager.getNotificationChannel(WATCH_CHANNEL);
            JSONObject record = new JSONObject();
            record.put("ok", true).put("runtime_permission_granted", permission)
                    .put("app_notifications_enabled", enabled)
                    .put("reply_channel", channelStatus(REPLY_CHANNEL, replies))
                    .put("watch_channel", channelStatus(WATCH_CHANNEL, watchChannel))
                    .put("interruption_filter", manager.getCurrentInterruptionFilter())
                    .put("heads_up_possible", permission && enabled && replies != null
                            && replies.getImportance() >= NotificationManager.IMPORTANCE_HIGH)
                    .put("heads_up_guaranteed", false).put("server_push", false);
            Intent settings = notificationSettingsIntent(context, replies != null);
            boolean channelSettings = replies != null;
            if (settings.resolveActivity(context.getPackageManager()) == null) {
                settings = notificationSettingsIntent(context, false);
                channelSettings = false;
            }
            record.put("settings_available", settings.resolveActivity(context.getPackageManager()) != null)
                    .put("settings_target", channelSettings ? "channel" : "app");
            return record.toString();
        } catch (RuntimeException | JSONException unavailable) {
            return "{\"ok\":false,\"error\":\"notification_status_unavailable\",\"heads_up_guaranteed\":false}";
        }
    }

    private static JSONObject channelStatus(String id, NotificationChannel channel) throws JSONException {
        JSONObject result = new JSONObject();
        result.put("id", id).put("exists", channel != null);
        if (channel == null) return result.put("importance", JSONObject.NULL)
                .put("importance_name", "unspecified").put("blocked", JSONObject.NULL);
        int importance = channel.getImportance();
        String name = importance == NotificationManager.IMPORTANCE_NONE ? "none"
                : importance == NotificationManager.IMPORTANCE_MIN ? "min"
                : importance == NotificationManager.IMPORTANCE_LOW ? "low"
                : importance == NotificationManager.IMPORTANCE_DEFAULT ? "default"
                : importance >= NotificationManager.IMPORTANCE_HIGH ? "high" : "unspecified";
        return result.put("importance", importance).put("importance_name", name)
                .put("blocked", importance == NotificationManager.IMPORTANCE_NONE);
    }

    static Intent notificationSettingsIntent(Context context, boolean channel) {
        return new Intent(channel ? Settings.ACTION_CHANNEL_NOTIFICATION_SETTINGS : Settings.ACTION_APP_NOTIFICATION_SETTINGS)
                .putExtra(Settings.EXTRA_APP_PACKAGE, context.getPackageName())
                .putExtra(Settings.EXTRA_CHANNEL_ID, REPLY_CHANNEL);
    }
    static void setObserver(Observer value) { observer = value; }
    static void clearObserver(Observer value) { if (observer == value) observer = null; }
    static void setAppForeground(boolean value) { synchronized (ADMISSION) { appForeground = value; } }
    static void setVisibleAccount(String server, String token) {
        synchronized (ADMISSION) {
            try { visibleAccount = ApiPolicy.jwt(token) ? accountKey(ApiPolicy.server(server), token) : ""; }
            catch (RuntimeException invalid) { visibleAccount = ""; }
        }
    }
    private static String accountKey(String server, String token) {
        return AttachmentCache.key(server, token, "reply-watch-account");
    }
    private static boolean isVisible(Watch selected) {
        return appForeground && selected != null && !visibleAccount.isEmpty()
                && visibleAccount.equals(accountKey(selected.server, selected.token));
    }

    static void preferencesChanged(Context context, NotificationPreferences preferences) {
        // Remove old previews immediately, including notices from a stopped watch.
        cancelNotices(context, null);
        ReplyWatchService active = current;
        synchronized (ADMISSION) { if (active != null) for (Watch selected : active.watches.values()) selected.notices.clear(); }
        if (!preferences.enabled) stop(context, "notifications_disabled");
    }

    static void cancelConversationNotices(Context context, String server, String token, String session) {
        cancelNotices(context, scope(server, token, session));
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        if (manager != null) cancelLegacyNotice(manager, authScope(server, token, session));
    }

    static int cancelMessageNotice(Context context, String server, String token, String session, String messageId) {
        String selectedScope = scope(server, token, session), tag = messageTag(selectedScope, messageId);
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        if (manager == null) return -1;
        int cancelled = 0;
        synchronized (ADMISSION) {
            // Only an explicitly opened saved message is cleared. Receiving a
            // history page is not proof that every message in it was opened.
            for (StatusBarNotification note : manager.getActiveNotifications())
                if (tag.equals(note.getTag()) && note.getId() == 4400
                        && REPLY_CHANNEL.equals(note.getNotification().getChannelId())) { manager.cancel(tag, 4400); cancelled++; }
            ReplyWatchService active = current;
            Watch selected = active == null ? null : active.watches.get(selectedScope);
            if (selected != null && selected.scope.equals(selectedScope) && selected.token.equals(token))
                selected.notices.removeIf(value -> messageId.equals(value.id));
        }
        // This is local cancellation, not a receipt or a human-read claim.
        return cancelled;
    }

    private static void cancelNotices(Context context, String scope) {
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        if (manager == null) return;
        String prefix = NOTICE_PREFIX + (scope == null ? "" : scope + ".");
        for (StatusBarNotification note : manager.getActiveNotifications())
            if (note.getTag() != null && note.getTag().startsWith(prefix)) manager.cancel(note.getTag(), note.getId());
        // Only known numeric notices on our replies channel can be legacy previews.
        if (scope != null) cancelLegacyNotice(manager, scope);
        else {
            SharedPreferences registration = context.getSharedPreferences("asteria_chat_reply_watch", Context.MODE_PRIVATE);
            cancelLegacyNotice(manager, registration.getString("scope", ""));
            cancelLegacyNotice(manager, registration.getString("registered_auth_scope", ""));
        }
    }

    private static void cancelLegacyNotice(NotificationManager manager, String knownScope) {
        if (knownScope == null || !knownScope.matches("[0-9a-f]{64}")) return;
        int knownId = 4400 + (knownScope.hashCode() & 0x3fff);
        for (StatusBarNotification note : manager.getActiveNotifications())
            if (note.getTag() == null && note.getId() == knownId && REPLY_CHANNEL.equals(note.getNotification().getChannelId()))
                manager.cancel(knownId);
    }

    static String messageTag(String scope, String messageId) { return NOTICE_PREFIX + scope + "." + AttachmentCache.digest(messageId); }

    private static void publish(String state, String reason, Watch value, boolean running, long nextPoll) {
        synchronized (ADMISSION) {
            if (value != null) {
                value.state = state; value.reason = reason == null ? "" : reason;
                value.nextPollAt = SystemClock.elapsedRealtime() + Math.max(0, nextPoll);
            }
            ReplyWatchService service = current;
            try { latest = service == null ? EMPTY_STATUS : statusSnapshot(service, null, reason).toString(); }
            catch (RuntimeException | JSONException unavailable) { latest = EMPTY_STATUS; }
            Observer listener = observer;
            if (listener != null) listener.changed(latest);
        }
    }

    static boolean acknowledge(String server, String token, String session, String messageId) {
        if (!appForeground || !positiveId(messageId)) return false;
        String normalized = ApiPolicy.server(server);
        AttachmentPolicy.session(session);
        if (!ApiPolicy.jwt(token)) return false;
        synchronized (ADMISSION) {
            ReplyWatchService active = current;
            Watch selected = active == null ? null : active.watches.get(scope(normalized, token, session));
            if (!isVisible(selected) || active == null || selected == null || !active.current(selected)
                    || !selected.token.equals(token) || !selected.scope.equals(scope(normalized, token, session))) return false;
            if (!messageId.equals(selected.cursor) && acceptsForegroundSyncCursor(selected.cursor, messageId, false))
                active.remember(selected, messageId);
            // Only the visible, authenticated page supplies a saved row ID.
            // Keep the later server sequence when a stale page acknowledges an older row.
            if (acceptsForegroundSyncCursor(selected.syncCursor, messageId, selected.syncBlocked)) {
                active.rememberSync(selected, messageId);
                selected.syncBlocked = false;
                selected.syncState = "foreground_reconciled";
            }
            selected.initialized = true;
            return true;
        }
    }

    static String start(Context context, String server, String token, String session, String title, String baseline) {
        if (!NotificationPreferences.load(context).enabled) throw new IllegalStateException("notifications_disabled");
        String normalized = ApiPolicy.server(server);
        AttachmentPolicy.session(session);
        if (!ApiPolicy.jwt(token)) throw new IllegalStateException("saved_login_required");
        synchronized (ADMISSION) {
            ReplyWatchAccounts.Record record = ReplyWatchAccounts.save(context, normalized, token, session, title, baseline);
            SharedPreferences saved = context.getSharedPreferences("asteria_chat_reply_watch", MODE_PRIVATE);
            forgetStoppedAccount(saved, record.id);
            if (!saved.edit().putBoolean("enabled", true).putBoolean("accounts_migrated", true)
                    .putBoolean("paused_" + record.id, false).remove("stop_reason_" + record.id).commit())
                throw new IllegalStateException("watch_registration_not_saved");
            ReplyWatchService active = current;
            Watch existing = active == null ? null : active.watches.get(record.id);
            if (existing != null && active.current(existing) && existing.token.equals(token)) return snapshot(context);
            if (existing != null) { active.watches.remove(existing.scope, existing); active.cancelRead(existing); }
            Intent command = new Intent(context, ReplyWatchService.class).setAction(START)
                    .putExtra("watch_id", record.id).putExtra("admission_epoch", ++admissionEpoch);
            startPending = true;
            try { context.startForegroundService(command); }
            catch (RuntimeException unavailable) {
                startPending = false;
                saved.edit().putString("stop_reason_" + record.id, "foreground_start_not_allowed").apply();
            }
            return snapshot(context);
        }
    }

    static void resumeEnabled(Context context) {
        synchronized (ADMISSION) {
            // Resume only a prior explicit registration while Activity is visible.
            // Keep a queued start's ticket so onResume cannot invalidate enrollment.
            if (!appForeground || startPending || !NotificationPreferences.load(context).enabled) return;
            ReplyWatchService active = current;
            if (active != null && active.running && !active.watches.isEmpty()) return;
            SharedPreferences saved = context.getSharedPreferences("asteria_chat_reply_watch", MODE_PRIVATE);
            if (!saved.getBoolean("enabled", false)) return;
            List<ReplyWatchAccounts.Record> records = ReplyWatchAccounts.list(context);
            boolean enabledTarget = false;
            for (ReplyWatchAccounts.Record record : records)
                if (!saved.getBoolean("paused_" + record.id, false)) { enabledTarget = true; break; }
            boolean legacy = records.isEmpty() && !saved.getBoolean("accounts_migrated", false)
                    && !saved.getString("registered_server", "").isEmpty()
                    && !saved.getString("registered_session", "").isEmpty();
            if (!enabledTarget && !legacy) return;
            Intent command = new Intent(context, ReplyWatchService.class).setAction(START)
                    .putExtra("admission_epoch", ++admissionEpoch);
            startPending = true;
            try { context.startForegroundService(command); }
            catch (RuntimeException unavailable) { startPending = false; }
        }
    }

    static void stopAccount(Context context, String server, String token, String reason) {
        if (!ApiPolicy.jwt(token)) return;
        String normalized = ApiPolicy.server(server), account = accountKey(normalized, token);
        synchronized (ADMISSION) {
            List<ReplyWatchAccounts.Record> records = ReplyWatchAccounts.list(context);
            ReplyWatchService active = current;
            for (ReplyWatchAccounts.Record record : records) {
                if (!account.equals(accountKey(record.server, record.token))) continue;
                context.getSharedPreferences("asteria_chat_reply_watch", MODE_PRIVATE).edit()
                        .putBoolean("paused_" + record.id, true).putString("stop_reason_" + record.id, reason).commit();
                Watch selected = active == null ? null : active.watches.get(record.id);
                if (selected != null) active.removeWatch(selected, reason);
                rememberStoppedAccount(context, record, reason);
                clearScopeNotices(context, record.id, authScope(record.server, record.token, record.session), true);
            }
            boolean removed = ReplyWatchAccounts.removeAccount(context, normalized, token);
            if (active != null) active.stopIfEmpty();
            latest = snapshot(context);
            if (!removed) throw new IllegalStateException("watch_registration_not_removed");
        }
    }

    static void stopTarget(Context context, String id, String reason) {
        synchronized (ADMISSION) {
            ReplyWatchAccounts.Record record = ReplyWatchAccounts.find(context, id);
            if (record == null) return;
            if (!context.getSharedPreferences("asteria_chat_reply_watch", MODE_PRIVATE).edit()
                    .putBoolean("paused_" + id, true).putString("stop_reason_" + id, reason).commit())
                throw new IllegalStateException("watch_stop_not_saved");
            ReplyWatchService active = current;
            Watch selected = active == null ? null : active.watches.get(id);
            if (selected != null) active.removeWatch(selected, reason);
            clearScopeNotices(context, id, authScope(record.server, record.token, record.session), false);
            if (active != null) active.stopIfEmpty();
            latest = snapshot(context);
        }
    }

    private static JSONArray stoppedAccounts(SharedPreferences saved) {
        try { return new JSONArray(saved.getString("stopped_accounts", "[]")); }
        catch (JSONException invalid) { return new JSONArray(); }
    }

    private static void forgetStoppedAccount(SharedPreferences saved, String id) {
        JSONArray previous = stoppedAccounts(saved), kept = new JSONArray();
        for (int index = 0; index < previous.length(); index++) {
            JSONObject row = previous.optJSONObject(index);
            if (row != null && !id.equals(row.optString("id"))) kept.put(row);
        }
        saved.edit().putString("stopped_accounts", kept.toString()).apply();
    }

    private static void rememberStoppedAccount(Context context, ReplyWatchAccounts.Record record, String reason) {
        SharedPreferences saved = context.getSharedPreferences("asteria_chat_reply_watch", MODE_PRIVATE);
        forgetStoppedAccount(saved, record.id);
        JSONArray previous = stoppedAccounts(saved), kept = new JSONArray();
        try {
            for (int index = Math.max(0, previous.length() - MAX_WATCHES + 1); index < previous.length(); index++)
                kept.put(previous.optJSONObject(index));
            kept.put(new JSONObject().put("id", record.id).put("account_id", record.id)
                    .put("server", record.server).put("username", record.username).put("session_id", record.session)
                    .put("title", record.title).put("active", false).put("running", false).put("enabled", false)
                    .put("registered", false).put("can_activate", false).put("verified_session", false)
                    .put("state", "stopped").put("reason", reason).put("last_stopped_at", System.currentTimeMillis()));
            saved.edit().putString("stopped_accounts", kept.toString()).apply();
        } catch (JSONException unavailable) { /* Credential removal must still proceed. */ }
    }

    static void stop(Context context, String reason) {
        synchronized (ADMISSION) {
            admissionEpoch++; startPending = false;
            SharedPreferences.Editor edit = context.getSharedPreferences("asteria_chat_reply_watch", MODE_PRIVATE).edit()
                    .putBoolean("enabled", false).putBoolean("accounts_migrated", true);
            for (ReplyWatchAccounts.Record record : ReplyWatchAccounts.list(context))
                edit.putBoolean("paused_" + record.id, true).putString("stop_reason_" + record.id, reason);
            edit.apply();
            ReplyWatchService active = current;
            if (active != null) active.finish(reason);
            else {
                clearPrivateNotices(context, reason);
                context.stopService(new Intent(context, ReplyWatchService.class));
                latest = snapshot(context);
            }
        }
    }

    static String notificationSession(Intent intent, String server, String token) {
        if (intent == null || !ApiPolicy.jwt(token)) return null;
        String session = intent.getStringExtra("session_id");
        try {
            AttachmentPolicy.session(session);
            String targetServer = intent.getStringExtra("reply_watch_server");
            if (targetServer != null && !ApiPolicy.server(server).equals(ApiPolicy.server(targetServer))) return null;
            String supplied = intent.getStringExtra("reply_watch_scope");
            return scope(server, token, session).equals(supplied) || authScope(server, token, session).equals(supplied) ? session : null;
        } catch (RuntimeException invalid) { return null; }
    }

    private static Intent openIntent(Context context, Watch selected) {
        return openIntent(context, selected, "", "conversation");
    }

    private static Intent openIntent(Context context, Watch selected, String messageId, String clickTarget) {
        return new Intent(context, MainActivity.class)
                .setData(Uri.parse("asteria-chat://reply/" + selected.scope + "/" + AttachmentCache.digest(messageId)))
                .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP | Intent.FLAG_ACTIVITY_CLEAR_TOP)
                .putExtra("session_id", selected.session).putExtra("reply_watch_scope", selected.scope)
                .putExtra("reply_watch_server", selected.server)
                .putExtra("reply_message_id", messageId).putExtra("reply_click_target", clickTarget);
    }

    static String scope(String server, String token, String session) {
        // Display/deduplication identity survives renewal of the same account JWT.
        // API request admission remains tied to the actual token via authScope.
        return AttachmentCache.key(server, token, "notification:" + session);
    }

    static String authScope(String server, String token, String session) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256").digest(
                    (server + "|" + token + "|" + session).getBytes(StandardCharsets.UTF_8));
            StringBuilder result = new StringBuilder(64);
            for (byte part : digest) result.append(String.format(java.util.Locale.ROOT, "%02x", part & 255));
            return result.toString();
        } catch (Exception unavailable) { throw new IllegalStateException("watch_identity_unavailable"); }
    }

    @Override public void onCreate() {
        super.onCreate();
        current = this;
        metadata = getSharedPreferences("asteria_chat_reply_watch", MODE_PRIVATE);
        NotificationManager manager = getSystemService(NotificationManager.class);
        if (manager != null) {
            NotificationChannel ongoing = new NotificationChannel(WATCH_CHANNEL, "后台回复监控", NotificationManager.IMPORTANCE_LOW);
            ongoing.setDescription("用户开启后，定期读取当前会话；可随时停止，不是服务器推送。");
            manager.createNotificationChannel(ongoing);
            if (manager.getNotificationChannel(REPLY_CHANNEL) == null)
                manager.createNotificationChannel(new NotificationChannel(REPLY_CHANNEL, "聊天回复", NotificationManager.IMPORTANCE_HIGH));
        }
    }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && STOP.equals(intent.getAction())) { finish("user_stopped"); return START_NOT_STICKY; }
        if (intent != null && !START.equals(intent.getAction())) return running ? START_STICKY : START_NOT_STICKY;
        synchronized (ADMISSION) {
            if (intent != null && intent.getLongExtra("admission_epoch", -1) != admissionEpoch)
                return running ? START_STICKY : START_NOT_STICKY;
            startPending = false;
            try {
                Notification initial = ongoing(null);
                if (Build.VERSION.SDK_INT >= 29) startForeground(WATCH_NOTIFICATION, initial, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC);
                else startForeground(WATCH_NOTIFICATION, initial);
                if (!notificationsAllowed()) { finish("notification_permission"); return START_NOT_STICKY; }
                if (!metadata.getBoolean("enabled", false)) { finish("not_enabled"); return START_NOT_STICKY; }
                migrateLegacyRegistration();
                for (ReplyWatchAccounts.Record record : ReplyWatchAccounts.list(this)) {
                    if (metadata.getBoolean("paused_" + record.id, false)) continue;
                    try { attach(record); }
                    catch (RuntimeException unavailable) {
                        metadata.edit().putBoolean("paused_" + record.id, true)
                                .putString("stop_reason_" + record.id, "watch_start_unavailable").apply();
                    }
                }
                stopIfEmpty();
            } catch (RuntimeException unavailable) { finish("restart_registration_unavailable"); }
        }
        return running ? START_STICKY : START_NOT_STICKY;
    }

    private void migrateLegacyRegistration() {
        if (metadata.getBoolean("accounts_migrated", false)) return;
        // Only an old explicitly enabled registration can be migrated from
        // TokenVault. Merely logging in never enrolls another account.
        if (ReplyWatchAccounts.list(this).isEmpty() && metadata.getBoolean("enabled", false)) {
            TokenVault vault = new TokenVault(this);
            try {
                String server = ApiPolicy.server(metadata.getString("registered_server", ""));
                String session = AttachmentPolicy.session(metadata.getString("registered_session", ""));
                String token = vault.load(server);
                if (server.equals(vault.server()) && ApiPolicy.jwt(token)
                        && authScope(server, token, session).equals(metadata.getString("registered_auth_scope", "")))
                    ReplyWatchAccounts.save(this, server, token, session,
                            metadata.getString("registered_title", BuildConfig.APP_NAME), metadata.getString("registered_baseline", ""));
            } catch (RuntimeException invalid) { /* Missing legacy credentials do not stop another account. */ }
        }
        if (!metadata.edit().putBoolean("accounts_migrated", true).commit())
            throw new IllegalStateException("watch_migration_not_saved");
    }

    static void credentialsChanged(Context context, String server, String token) {
        if (!ApiPolicy.jwt(token)) return;
        String normalized = ApiPolicy.server(server), account = accountKey(normalized, token);
        synchronized (ADMISSION) {
            for (ReplyWatchAccounts.Record record : ReplyWatchAccounts.list(context)) {
                if (!account.equals(accountKey(record.server, record.token))) continue;
                ReplyWatchAccounts.Record renewed = ReplyWatchAccounts.save(context, normalized, token,
                        record.session, record.title, record.baseline);
                ReplyWatchService active = current;
                if (active != null && active.watches.containsKey(record.id)) active.attach(renewed);
            }
        }
    }

    private void attach(ReplyWatchAccounts.Record record) {
        if (!record.id.equals(scope(record.server, record.token, record.session)) || !ReplyWatchAccounts.matches(this, record))
            throw new IllegalStateException("watch_registration_changed");
        Watch previous = watches.get(record.id);
        if (previous != null && current(previous) && previous.token.equals(record.token)) return;
        if (previous == null && watches.size() >= MAX_WATCHES) throw new IllegalStateException("watch_account_limit");
        if (previous != null) { watches.remove(previous.scope, previous); cancelRead(previous); }
        Watch selected = new Watch(record);
        watches.put(selected.scope, selected); running = true;
        String legacy = selected.scope.equals(metadata.getString("scope", "")) ? metadata.getString("last_seen_id", "") : "";
        if (previous != null) selected.lastNetworkStarted = previous.lastNetworkStarted;
        selected.cursor = latestCursor(metadata.getString("last_seen_" + selected.scope, ""), legacy, selected.baseline);
        selected.syncCursor = latestCursor(metadata.getString("sync_after_" + selected.scope, ""), selected.cursor);
        selected.syncBlocked = metadata.getBoolean("sync_blocked_" + selected.scope, false);
        if (selected.syncBlocked) selected.syncState = "cursor_unavailable";
        selected.uncertainNotices = uncertainNotices(selected);
        publish("starting", null, selected, true, 0);
        schedule(selected, nextAllowedDelay(selected));
    }

    private long nextAllowedDelay(Watch selected) {
        synchronized (selected) { return Math.max(0, POLL_MS - (SystemClock.elapsedRealtime() - selected.lastNetworkStarted)); }
    }

    private void schedule(Watch selected, long delay) {
        if (!current(selected)) return;
        selected.nextPollAt = SystemClock.elapsedRealtime() + Math.max(0, delay);
        try { selected.pending = executor.schedule(() -> {
            if (!current(selected) || !selected.polling.compareAndSet(false, true)) return;
            try { poll(selected); } finally { selected.polling.set(false); }
        }, Math.max(0, delay), TimeUnit.MILLISECONDS); }
        catch (RuntimeException stopped) { finishWatch(selected, "watch_stopped"); }
    }

    private boolean current(Watch selected) {
        return selected != null && running && watches.get(selected.scope) == selected && current == this;
    }

    private void removeWatch(Watch selected, String reason) {
        if (!watches.remove(selected.scope, selected)) return;
        cancelRead(selected); rememberStop(selected, reason);
        metadata.edit().putBoolean("paused_" + selected.scope, true).apply();
        if (privateStop(reason)) clearScopeNotices(this, selected.scope, authScope(selected.server, selected.token, selected.session), true);
        selected.state = "stopped"; selected.reason = reason;
        publish("stopped", reason, selected, false, 0);
    }

    private void stopIfEmpty() {
        if (!watches.isEmpty()) {
            running = true;
            NotificationManager manager = getSystemService(NotificationManager.class);
            if (manager != null) manager.notify(WATCH_NOTIFICATION, ongoing(null));
            return;
        }
        running = false;
        final long stoppingTicket = admissionEpoch;
        main.post(() -> {
            synchronized (ADMISSION) {
                if (stoppingTicket != admissionEpoch || !watches.isEmpty()) return;
                stopForeground(STOP_FOREGROUND_REMOVE); stopSelf();
            }
        });
    }

    private void finishWatch(Watch selected, String reason) {
        synchronized (ADMISSION) {
            if (!current(selected)) return;
            removeWatch(selected, reason);
            stopIfEmpty();
        }
    }

    private void rejectWatch(Watch selected, int status) {
        synchronized (ADMISSION) {
            // A response from an old token must not revoke a newly renewed login.
            if (!current(selected)) return;
            if (status == 401) stopAccount(this, selected.server, selected.token, "login_expired");
            else finishWatch(selected, "session_unavailable");
        }
    }

    private void updateWatch(Watch selected, String state, String reason, long delay) {
        synchronized (ADMISSION) { if (current(selected)) publish(state, reason, selected, true, delay); }
    }

    private void poll(Watch selected) {
        if (!current(selected)) return;
        if (!notificationsAllowed()) { finish("notification_permission"); return; }
        if (selected.registration != null && !ReplyWatchAccounts.matches(this, selected.registration)) { finishWatch(selected, "authentication_changed"); return; }
        // The visible page owns its one history coordinator. Do not create a
        // second foreground read or advance a cursor for content it has not read.
        if (isVisible(selected)) {
            updateWatch(selected, "running", "foreground_ui_owns_reads", POLL_MS);
            schedule(selected, POLL_MS);
            return;
        }
        if (selected.syncBlocked) {
            updateWatch(selected, "running", "cursor_unavailable_open_chat", POLL_MS);
            schedule(selected, POLL_MS);
            return;
        }
        synchronized (selected) {
            long delay = POLL_MS - (SystemClock.elapsedRealtime() - selected.lastNetworkStarted);
            if (delay > 0) { schedule(selected, delay); return; }
            if (!current(selected)) return;
            selected.lastNetworkStarted = SystemClock.elapsedRealtime();
        }
        HttpsURLConnection request = null;
        long delay = POLL_MS;
        boolean incremental = selected.syncSupported && positiveId(selected.syncCursor);
        String requestAfter = selected.syncCursor;
        try {
            String endpoint = incremental ? "/chat/sync?session_id=" : "/chat/history?session_id=";
            String query = endpoint + URLEncoder.encode(selected.session, "UTF-8")
                    + (incremental ? "&after_id=" + requestAfter + "&limit=32" : "");
            String path = ApiPolicy.requestPath(query);
            request = (HttpsURLConnection) new URL(selected.server + path).openConnection();
            selected.connection = request;
            PinnedTls.configure(request, selected.server);
            request.setInstanceFollowRedirects(false);
            request.setConnectTimeout(10000); request.setReadTimeout(15000);
            request.setRequestMethod("GET");
            request.setRequestProperty("Accept", "application/json");
            request.setRequestProperty("User-Agent", "AsteriaChat/" + BuildConfig.VERSION_NAME + " ReplyWatch");
            request.setRequestProperty("Authorization", "Bearer " + selected.token);
            if (!current(selected)) return;
            int status = request.getResponseCode();
            if (!current(selected)) return;
            if (status == 401 || status == 403 || status == 404) {
                rejectWatch(selected, status); return;
            }
            if (status < 200 || status >= 300) throw new java.io.IOException("history_unavailable");
            JSONObject envelope = new JSONObject(read(request.getInputStream()));
            if (envelope.has("status") && !"ok".equals(envelope.optString("status")))
                throw new java.io.IOException("history_not_successful");
            JSONObject data = envelope.optJSONObject("data");
            if (data == null) data = envelope;
            JSONArray history = data.optJSONArray("history");
            if (history == null) throw new java.io.IOException("history_shape_unavailable");
            if (incremental && (data.optBoolean("reset_required") || !data.optBoolean("anchor_found"))) {
                synchronized (ADMISSION) {
                    if (!current(selected) || isVisible(selected) || !requestAfter.equals(selected.syncCursor)) return;
                    if (!metadata.edit().putBoolean("sync_blocked_" + selected.scope, true).commit())
                        throw new IllegalStateException("watch_gap_not_saved");
                    selected.syncBlocked = true; selected.syncState = "cursor_unavailable";
                }
                updateWatch(selected, "running", "cursor_unavailable_open_chat", delay);
                return;
            }
            String nextCursor = incremental ? syncNext(data, requestAfter, history) : "";
            List<JSONObject> assistants = new ArrayList<>();
            for (int index = 0; index < history.length(); index++) {
                JSONObject row = history.optJSONObject(index);
                if (row == null || row.isNull("id")) continue;
                JSONObject content = row.optJSONObject("content");
                String id = String.valueOf(row.opt("id"));
                if (content != null && "bot".equals(content.optString("type")) && !id.isEmpty() && id.length() <= 160)
                    assistants.add(row);
            }
            if (!current(selected)) return;
            selected.verified = true;
            JSONObject receipts = data.optJSONObject("receipt_transport");
            selected.receiptsSupported = receipts != null && receipts.optInt("schema") == 1 && receipts.optBoolean("supported");
            JSONObject sync = receipts == null ? null : receipts.optJSONObject("message_sync");
            if (sync == null) sync = data.optJSONObject("message_sync");
            selected.syncSupported = sync != null && sync.optInt("schema") == 1 && sync.optBoolean("supported")
                    && "saved_rows_after_id".equals(sync.optString("mode"));
            if (isVisible(selected) || !requestAfter.equals(selected.syncCursor)) { updateWatch(selected, "running", "foreground_ui_owns_reads", delay); return; }
            if (selected.receiptsSupported) {
                List<String> received = new ArrayList<>();
                List<String> alreadyPosted = new ArrayList<>();
                for (int index = Math.max(0, assistants.size() - 32); index < assistants.size(); index++)
                    received.add(String.valueOf(assistants.get(index).opt("id")));
                queueReceipts(selected, received, "client_received");
                for (JSONObject row : assistants) {
                    String id = String.valueOf(row.opt("id"));
                    if ("posted".equals(noticeDisposition(selected, id))) alreadyPosted.add(id);
                }
                // A process may end after notify/its local outcome was saved
                // but before the monotonic server receipt was queued.
                queueReceipts(selected, alreadyPosted, "system_notification_posted");
            }
            if (incremental) {
                synchronized (ADMISSION) {
                    if (!requestAfter.equals(selected.syncCursor) || !reconcile(selected, assistants, true)) return;
                    if (!rememberBackgroundSync(selected, nextCursor, requestAfter)) return;
                }
                selected.syncState = data.optBoolean("has_more") ? "catching_up" : "synced";
            } else if (selected.syncSupported && positiveId(selected.syncCursor)) {
                // Discover capability without discarding the older durable cursor
                // merely because it is outside the legacy recent-history window.
                selected.syncState = "catching_up";
            } else {
                reconcile(selected, assistants);
                if (selected.syncSupported && history.length() > 0) {
                    String latestId = String.valueOf(history.optJSONObject(history.length() - 1).opt("id"));
                    if (positiveId(latestId) && !rememberBackgroundSync(selected, latestId, requestAfter)) return;
                }
                selected.syncState = selected.syncSupported ? "baseline_saved" : "legacy_history_window";
            }
            selected.lastSyncAt = System.currentTimeMillis();
            if (!current(selected)) return;
            // Close this account's history IO before its receipt POSTs.
            // At most two independent account workers perform network IO.
            request.disconnect();
            if (selected.connection == request) selected.connection = null;
            if (selected.receiptsSupported) flushReceipts(selected, assistants);
            selected.failures = 0;
            synchronized (ADMISSION) {
                if (!current(selected)) return;
                publish("running", null, selected, true, delay);
                NotificationManager manager = getSystemService(NotificationManager.class);
                if (manager != null) manager.notify(WATCH_NOTIFICATION, ongoing(selected));
            }
        } catch (Exception unavailable) {
            if (!current(selected)) return;
            selected.failures = Math.min(4, selected.failures + 1);
            delay = Math.min(300000, POLL_MS * (1L << selected.failures));
            updateWatch(selected, "reconnecting", unavailable instanceof IllegalStateException
                    ? "local_delivery_state_unavailable" : "network_or_history_unavailable", delay);
        } finally {
            if (request != null) request.disconnect();
            if (selected.connection == request) selected.connection = null;
            if (current(selected)) schedule(selected, delay);
        }
    }

    private void reconcile(Watch selected, List<JSONObject> rows) {
        reconcile(selected, rows, false);
    }

    private boolean reconcile(Watch selected, List<JSONObject> rows, boolean incremental) {
        String newest = rows.isEmpty() ? "" : String.valueOf(rows.get(rows.size() - 1).opt("id"));
        if (!incremental && !selected.initialized) {
            selected.initialized = true;
            String saved = metadata.getString("last_seen_" + selected.scope, "");
            selected.cursor = latestCursor(saved, selected.baseline);
            if (selected.cursor.isEmpty()) { remember(selected, newest); return true; }
        }
        int anchor = -1;
        if (!incremental && !selected.cursor.isEmpty()) {
            for (int index = 0; index < rows.size(); index++)
                if (selected.cursor.equals(String.valueOf(rows.get(index).opt("id")))) anchor = index;
            // The saved cursor fell outside the server's bounded history; do
            // not turn unknown older records into a batch of fresh alerts.
            if (anchor < 0) { selected.syncState = "legacy_cursor_outside_window"; remember(selected, newest); return true; }
        }
        if (!current(selected) || isVisible(selected)) return false;
        if (!notificationsAllowed()) { finish("notification_permission"); return false; }
        NotificationManager manager = getSystemService(NotificationManager.class);
        if (manager == null) throw new IllegalStateException("notification_manager_unavailable");
        NotificationPreferences preferences = NotificationPreferences.load(this);
        // Updating the same durable server ID replaces the same Android tag. A
        // hidden/quiet category still advances our cursor, and is never replayed later.
        List<NoticeMessage> incoming = newNoticeMessages(rows, anchor, System.currentTimeMillis());
        for (NoticeMessage value : incoming) for (JSONObject row : rows) if (value.id.equals(String.valueOf(row.opt("id")))) {
            value.kind = noticeKind(row); value.imageFilename = imageFilename(row); break;
        }
        synchronized (ADMISSION) {
            if (!current(selected) || isVisible(selected)) return false;
            List<NoticeMessage> allowed = new ArrayList<>();
            for (NoticeMessage value : incoming)
                if (preferences.allows(value.kind, java.util.Calendar.getInstance())) allowed.add(value);
            List<NoticeMessage> previous = new ArrayList<>(selected.notices);
            mergeNoticeMessages(selected.notices, allowed);
            for (NoticeMessage old : previous) if (!selected.notices.contains(old)) manager.cancel(messageTag(selected.scope, old.id), 4400);
            List<String> posted = new ArrayList<>();
            for (NoticeMessage value : allowed) {
                String disposition = noticeDisposition(selected, value.id);
                if ("posted".equals(disposition)) { posted.add(value.id); continue; }
                if (!disposition.isEmpty()) continue;
                // Android notify and local storage cannot form one transaction.
                // Retain a pre-call marker so process death or an ambiguous
                // exception never resurrects a dismissed notification.
                rememberDisposition(selected, value.id, "posting");
                postNotice(selected, value, preferences, manager);
                rememberDisposition(selected, value.id, "posted");
                posted.add(value.id);
            }
            trimNotices(manager, selected.scope);
            // A corrected saved row updates only a still-present notice. It
            // never resurrects a dismissed notification or creates a new receipt.
            for (NoticeMessage old : previous) for (JSONObject row : rows) {
                if (!old.id.equals(String.valueOf(row.opt("id")))) continue;
                String changed = preview(row);
                if (!changed.isEmpty() && (!changed.equals(old.text) || !imageFilename(row).equals(old.imageFilename)
                        || !noticeKind(row).equals(old.kind)) && hasNotice(manager, messageTag(selected.scope, old.id))) {
                    NoticeMessage revised = new NoticeMessage(old.id, changed, old.timestamp);
                    revised.kind = noticeKind(row); revised.imageFilename = imageFilename(row);
                    if (preferences.allows(revised.kind, java.util.Calendar.getInstance())) {
                        int index = selected.notices.indexOf(old);
                        if (index >= 0) selected.notices.set(index, revised);
                        postNotice(selected, revised, preferences, manager);
                    } else manager.cancel(messageTag(selected.scope, old.id), 4400);
                }
            }
            // notify returning proves a publish call, not a banner or a human read.
            if (selected.receiptsSupported) queueReceipts(selected, posted, "system_notification_posted");
            if (!newest.isEmpty()) remember(selected, newest);
        }
        return true;
    }

    private static boolean hasNotice(NotificationManager manager, String tag) {
        for (StatusBarNotification note : manager.getActiveNotifications()) if (tag.equals(note.getTag())) return true;
        return false;
    }

    private static void trimNotices(NotificationManager manager, String scope) {
        List<StatusBarNotification> notices = new ArrayList<>();
        for (StatusBarNotification note : manager.getActiveNotifications())
            if (note.getTag() != null && note.getTag().startsWith(NOTICE_PREFIX + scope + ".")) notices.add(note);
        notices.sort(java.util.Comparator.comparingLong(StatusBarNotification::getPostTime));
        for (int index = 0; index < notices.size() - MAX_NOTICE_MESSAGES; index++) {
            StatusBarNotification old = notices.get(index); manager.cancel(old.getTag(), old.getId());
        }
    }

    private void postNotice(Watch selected, NoticeMessage message, NotificationPreferences preferences, NotificationManager manager) {
        String tag = messageTag(selected.scope, message.id);
        NotificationIdentity identity = NotificationIdentity.load(this, selected.scope, selected.title);
        manager.notify(tag, 4400, conversationNotification(selected, message, preferences, identity, null));
        // Text is already posted. Enrich from a validated local attachment only;
        // no network, second poller, retry, or image failure can delay that text.
        if (!preferences.preview || message.imageFilename.isEmpty()) return;
        try {
            String path = AttachmentPolicy.downloadPath(selected.session, message.imageFilename);
            AttachmentCache.Entry image = AttachmentCache.find(this, AttachmentCache.key(selected.server, selected.token, path));
            if (image == null || !AttachmentPolicy.previewImage(image.mime)) return;
            byte[] header = new byte[12]; int count;
            try (InputStream input = new java.io.FileInputStream(image.file)) { count = input.read(header); }
            if (count < 3 || !image.mime.equals(AttachmentPolicy.imageSignature(java.util.Arrays.copyOf(header, count)))) return;
            Uri uri = AttachmentFileProvider.publish(this, image.file, message.imageFilename, image.mime);
            if (current(selected) && !isVisible(selected) && hasNotice(manager, tag))
                manager.notify(tag, 4400, conversationNotification(selected, message, preferences, identity, new CachedNoticeImage(uri, image.mime)));
        } catch (Exception unavailable) { /* Keep the already posted text. */ }
    }

    private static final class CachedNoticeImage {
        final Uri uri; final String mime;
        CachedNoticeImage(Uri uri, String mime) { this.uri = uri; this.mime = mime; }
    }

    private static String imageFilename(JSONObject row) {
        JSONArray parts = row.optJSONArray("tls_parts"); JSONObject content = row.optJSONObject("content");
        if ((parts == null || parts.length() == 0) && content != null) parts = content.optJSONArray("message");
        if (parts != null) for (int i = 0; i < parts.length(); i++) {
            JSONObject part = parts.optJSONObject(i);
            if (part == null || !"image".equals(part.optString("type"))) continue;
            String name = part.optString("stored_filename", part.optString("filename"));
            try { return AttachmentPolicy.filename(name); } catch (RuntimeException invalid) { }
        }
        return "";
    }

    private JSONObject receiptMap(Watch selected, String name) throws JSONException {
        return new JSONObject(metadata.getString(name + selected.scope, "{}"));
    }

    private void queueReceipts(Watch selected, List<String> ids, String phase) {
        if (ids.isEmpty() || !current(selected)) return;
        try {
            JSONObject pending = receiptMap(selected, "receipt_pending_"), done = receiptMap(selected, "receipt_done_");
            for (String id : ids) {
                if (id.isEmpty() || id.length() > 160) continue;
                JSONObject confirmed = done.optJSONObject(id);
                if (confirmed != null && confirmed.optBoolean(phase)) continue;
                JSONObject item = pending.optJSONObject(id);
                if (item == null) { item = new JSONObject(); pending.put(id, item); }
                item.put(phase, true);
            }
            while (pending.length() > 64) pending.remove(pending.keys().next());
            if (!metadata.edit().putString("receipt_pending_" + selected.scope, pending.toString()).commit())
                throw new IllegalStateException("receipt_pending_not_saved");
            if (pending.length() > 0) selected.receiptState = "pending";
        } catch (RuntimeException | JSONException unavailable) {
            selected.receiptState = "local_receipt_save_failed";
        }
    }

    private void flushReceipts(Watch selected, List<JSONObject> history) {
        try {
            JSONObject pending = receiptMap(selected, "receipt_pending_"), done = receiptMap(selected, "receipt_done_");
            for (String phase : new String[] { "client_received", "system_notification_posted" }) {
                if (!current(selected) || isVisible(selected)) return;
                JSONArray ids = new JSONArray();
                for (java.util.Iterator<String> keys = pending.keys(); keys.hasNext() && ids.length() < 32;) {
                    String id = keys.next();
                    JSONObject value = pending.optJSONObject(id);
                    // This scoped queue was created only from actual saved
                    // history observations. Incremental pages move forward,
                    // so a lost receipt must not require its old row to appear
                    // again in the current page. The server rechecks each ID
                    // against the original owned session before accepting it.
                    if (positiveId(id) && value != null && value.optBoolean(phase)) ids.put(id);
                }
                if (ids.length() == 0) continue;
                JSONObject body = new JSONObject().put("session_id", selected.session).put("phase", phase).put("message_ids", ids);
                HttpsURLConnection report = null;
                try {
                    report = (HttpsURLConnection) new URL(selected.server + ApiPolicy.requestPath("/chat/receipts")).openConnection();
                    selected.connection = report;
                    PinnedTls.configure(report, selected.server);
                    report.setInstanceFollowRedirects(false);
                    report.setConnectTimeout(5000); report.setReadTimeout(5000);
                    report.setRequestMethod("POST"); report.setDoOutput(true);
                    report.setRequestProperty("Content-Type", "application/json; charset=utf-8");
                    report.setRequestProperty("Authorization", "Bearer " + selected.token);
                    byte[] raw = body.toString().getBytes(StandardCharsets.UTF_8);
                    report.setFixedLengthStreamingMode(raw.length);
                    if (!current(selected) || isVisible(selected)) return;
                    try (OutputStream stream = report.getOutputStream()) { stream.write(raw); }
                    int status = report.getResponseCode();
                    if (status == 401 || status == 403 || status == 404) {
                        finishWatch(selected, status == 401 ? "login_expired" : "session_unavailable"); return;
                    }
                    if (status != 200) throw new java.io.IOException("receipt_not_confirmed");
                    JSONObject answer = new JSONObject(read(report.getInputStream()));
                    if (!"ok".equals(answer.optString("status")) || answer.optJSONObject("data") == null)
                        throw new java.io.IOException("receipt_not_confirmed");
                    if (!current(selected)) return;
                    for (int index = 0; index < ids.length(); index++) {
                        String id = ids.getString(index);
                        JSONObject value = pending.optJSONObject(id), confirmed = done.optJSONObject(id);
                        if (confirmed == null) { confirmed = new JSONObject(); done.put(id, confirmed); }
                        confirmed.put(phase, true);
                        if (value != null) { value.remove(phase); if (value.length() == 0) pending.remove(id); }
                    }
                    while (done.length() > 64) done.remove(done.keys().next());
                    if (!metadata.edit().putString("receipt_pending_" + selected.scope, pending.toString())
                            .putString("receipt_done_" + selected.scope, done.toString()).commit())
                        throw new IllegalStateException("receipt_result_not_saved");
                    selected.receiptState = pending.length() == 0 ? "synced" : "pending";
                } finally {
                    if (report != null) report.disconnect();
                    if (selected.connection == report) selected.connection = null;
                }
            }
        } catch (Exception unavailable) {
            // Lost acknowledgements repeat only this monotonic metadata report
            // on a later normal poll. Never repeat the chat send or notify call.
            selected.receiptState = "receipt_sync_pending";
        }
    }

    private static List<NoticeMessage> newNoticeMessages(List<JSONObject> rows, int anchor, long receivedAt) {
        List<NoticeMessage> result = new ArrayList<>();
        for (int index = Math.max(0, anchor + 1); index < rows.size(); index++) {
            JSONObject row = rows.get(index);
            String value = preview(row);
            if (value.isEmpty()) continue;
            result.add(new NoticeMessage(String.valueOf(row.opt("id")), value, messageTime(row, receivedAt)));
            if (result.size() > MAX_NOTICE_MESSAGES) result.remove(0);
        }
        return result;
    }

    private static void mergeNoticeMessages(List<NoticeMessage> previous, List<NoticeMessage> incoming) {
        for (NoticeMessage value : incoming) {
            boolean known = false;
            for (NoticeMessage old : previous) if (old.id.equals(value.id)) { known = true; break; }
            if (!known) previous.add(value);
        }
        while (previous.size() > MAX_NOTICE_MESSAGES) previous.remove(0);
    }

    private static long messageTime(JSONObject row, long receivedAt) {
        String value = row.optString("created_at").trim().replace(' ', 'T');
        try { return java.time.Instant.parse(value).toEpochMilli(); }
        catch (RuntimeException unavailable) {
            try { return java.time.OffsetDateTime.parse(value).toInstant().toEpochMilli(); }
            catch (RuntimeException unknownZone) { return receivedAt; }
        }
    }

    private Notification conversationNotification(Watch selected, NoticeMessage message,
            NotificationPreferences preferences, NotificationIdentity identity, CachedNoticeImage image) {
        String visibleText = preferences.preview ? message.text : "你收到一条新消息，打开查看";
        Bitmap portrait = identity.portrait();
        Notification.MessagingStyle style;
        if (Build.VERSION.SDK_INT >= 28) {
            Person self = new Person.Builder().setName("我").build();
            Person.Builder author = new Person.Builder().setName(identity.name).setKey(selected.scope)
                    .setUri("asteria-chat://person/" + selected.scope).setBot(true);
            if (portrait != null) author.setIcon(Icon.createWithBitmap(portrait));
            style = new Notification.MessagingStyle(self).setGroupConversation(false);
            Notification.MessagingStyle.Message line = new Notification.MessagingStyle.Message(visibleText, message.timestamp, author.build());
            if (image != null) line.setData(image.mime, image.uri);
            style.addMessage(line);
        } else {
            style = new Notification.MessagingStyle("我");
            Notification.MessagingStyle.Message line = new Notification.MessagingStyle.Message(visibleText, message.timestamp, identity.name);
            if (image != null) line.setData(image.mime, image.uri);
            style.addMessage(line);
        }
        style.setConversationTitle(identity.name);
        PendingIntent open = PendingIntent.getActivity(this, replyId(selected),
                openIntent(this, selected, message.id, preferences.clickTarget), PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        Notification publicVersion = new Notification.Builder(this, REPLY_CHANNEL).setSmallIcon(R.drawable.ic_notification)
                .setContentTitle(BuildConfig.APP_NAME).setContentText("收到新消息").build();
        Notification.Builder note = new Notification.Builder(this, REPLY_CHANNEL)
                .setSmallIcon(R.drawable.ic_notification)
                .setContentTitle(noticeTitle(message.kind, identity.name)).setContentText(visibleText)
                .setCategory("reminder".equals(message.kind) ? Notification.CATEGORY_REMINDER : Notification.CATEGORY_MESSAGE)
                .setStyle(style).setVisibility(Notification.VISIBILITY_PRIVATE).setPublicVersion(publicVersion)
                .setGroup("asteria-chat.conversation." + selected.scope).setOnlyAlertOnce(true)
                .setAutoCancel(true).setContentIntent(open);
        if (portrait != null) note.setLargeIcon(portrait);
        if (publishConversationShortcut(selected, identity, portrait)) note.setShortcutId(SHORTCUT_PREFIX + selected.scope);
        return note.build();
    }

    private boolean publishConversationShortcut(Watch selected, NotificationIdentity identity, Bitmap portrait) {
        if (Build.VERSION.SDK_INT < 29) return false;
        try {
            ShortcutManager shortcuts = getSystemService(ShortcutManager.class);
            if (shortcuts == null) return false;
            Person.Builder author = new Person.Builder().setName(identity.name).setKey(selected.scope).setBot(true);
            if (portrait != null) author.setIcon(Icon.createWithBitmap(portrait));
            ShortcutInfo.Builder builder = new ShortcutInfo.Builder(this, SHORTCUT_PREFIX + selected.scope)
                    .setShortLabel(identity.name).setLongLabel(identity.name)
                    .setIntent(openIntent(this, selected).setAction(Intent.ACTION_VIEW))
                    .setPersons(new Person[] { author.build() }).setLongLived(true)
                    .setCategories(Collections.singleton("android.shortcut.conversation"));
            if (portrait != null) builder.setIcon(Icon.createWithBitmap(portrait));
            ShortcutInfo shortcut = builder.build();
            if (Build.VERSION.SDK_INT >= 30) { shortcuts.pushDynamicShortcut(shortcut); return true; }
            return shortcuts.addDynamicShortcuts(Collections.singletonList(shortcut));
        } catch (RuntimeException unavailable) { return false; }
    }

    private void remember(Watch selected, String id) {
        synchronized (ADMISSION) {
            if (!current(selected)) return;
            if (!metadata.edit().putString("last_seen_" + selected.scope, id).commit())
                throw new IllegalStateException("watch_cursor_not_saved");
            selected.cursor = id;
        }
    }

    private static boolean positiveId(String value) {
        if (value == null || !value.matches("[1-9][0-9]{0,18}")) return false;
        try { return Long.parseLong(value) > 0; } catch (NumberFormatException invalid) { return false; }
    }

    private static String latestCursor(String... values) {
        String result = "";
        for (String value : values) {
            if (positiveId(value)) {
                if (!positiveId(result) || Long.parseLong(value) > Long.parseLong(result)) result = value;
            } else if (result.isEmpty() && value != null && !value.isEmpty()) result = value;
        }
        return result;
    }

    private static boolean acceptsForegroundSyncCursor(String saved, String visible, boolean gap) {
        // A reported deleted/ahead cursor is explicitly reconciled only after
        // the user opens the real, authenticated foreground history. This may
        // rebase lower; a routine stale-page acknowledgement must not do so.
        return positiveId(visible) && (gap || !positiveId(saved) || Long.parseLong(visible) >= Long.parseLong(saved));
    }

    private static String syncNext(JSONObject data, String after, JSONArray rows) throws java.io.IOException {
        String next = data.optString("next_after_id");
        if (!positiveId(after) || !positiveId(next)) throw new java.io.IOException("sync_cursor_unavailable");
        long previous = Long.parseLong(after);
        for (int index = 0; index < rows.length(); index++) {
            JSONObject row = rows.optJSONObject(index);
            String id = row == null ? "" : String.valueOf(row.opt("id"));
            if (!positiveId(id) || Long.parseLong(id) <= previous) throw new java.io.IOException("sync_order_unavailable");
            previous = Long.parseLong(id);
        }
        if (previous != Long.parseLong(next) || rows.length() > 32 || (rows.length() == 0 && data.optBoolean("has_more")))
            throw new java.io.IOException("sync_page_unavailable");
        return next;
    }

    private void rememberSync(Watch selected, String id) {
        synchronized (ADMISSION) {
            if (!current(selected)) return;
            if (!positiveId(id)) throw new IllegalArgumentException("invalid_sync_cursor");
            if (!metadata.edit().putString("sync_after_" + selected.scope, id)
                    .putBoolean("sync_blocked_" + selected.scope, false).commit())
                throw new IllegalStateException("sync_cursor_not_saved");
            selected.syncCursor = id;
        }
    }

    private boolean rememberBackgroundSync(Watch selected, String id, String expected) {
        synchronized (ADMISSION) {
            if (!current(selected) || isVisible(selected) || !expected.equals(selected.syncCursor)) return false;
            rememberSync(selected, id);
            return true;
        }
    }

    private String noticeDisposition(Watch selected, String id) {
        try {
            JSONObject row = new JSONObject(metadata.getString("notice_dispositions_" + selected.scope, "{}"));
            JSONObject value = row.optJSONObject(id);
            return value == null ? "" : value.optString("state", "posting");
        } catch (JSONException invalid) { throw new IllegalStateException("notice_disposition_unavailable", invalid); }
    }

    private void rememberDisposition(Watch selected, String id, String state) {
        if (!current(selected)) throw new IllegalStateException("watch_stopped");
        try {
            JSONObject rows = new JSONObject(metadata.getString("notice_dispositions_" + selected.scope, "{}"));
            rows.put(id, new JSONObject().put("state", state).put("at", System.currentTimeMillis()));
            while (rows.length() > 64) {
                String oldest = null; long at = Long.MAX_VALUE;
                for (java.util.Iterator<String> keys = rows.keys(); keys.hasNext();) {
                    String key = keys.next(); JSONObject row = rows.optJSONObject(key);
                    long saved = row == null ? 0 : row.optLong("at");
                    if (saved < at && !key.equals(id)) { oldest = key; at = saved; }
                }
                if (oldest == null) throw new IllegalStateException("notice_disposition_capacity");
                rows.remove(oldest);
            }
            if (!metadata.edit().putString("notice_dispositions_" + selected.scope, rows.toString()).commit())
                throw new IllegalStateException("notice_disposition_not_saved");
            selected.uncertainNotices = uncertainNotices(selected);
        } catch (JSONException invalid) { throw new IllegalStateException("notice_disposition_unavailable", invalid); }
    }

    private int uncertainNotices(Watch selected) {
        try {
            JSONObject rows = new JSONObject(metadata.getString("notice_dispositions_" + selected.scope, "{}"));
            int count = 0;
            for (java.util.Iterator<String> keys = rows.keys(); keys.hasNext();) {
                JSONObject row = rows.optJSONObject(keys.next());
                if (row != null && !"posted".equals(row.optString("state"))) count++;
            }
            return count;
        } catch (JSONException invalid) { return -1; }
    }

    private boolean notificationsAllowed() {
        if (!NotificationPreferences.load(this).enabled) return false;
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission("android.permission.POST_NOTIFICATIONS") != PackageManager.PERMISSION_GRANTED) return false;
        NotificationManager manager = getSystemService(NotificationManager.class);
        if (manager == null || !manager.areNotificationsEnabled()) return false;
        NotificationChannel watched = manager.getNotificationChannel(WATCH_CHANNEL);
        NotificationChannel replies = manager.getNotificationChannel(REPLY_CHANNEL);
        return (watched == null || watched.getImportance() != NotificationManager.IMPORTANCE_NONE)
                && (replies == null || replies.getImportance() != NotificationManager.IMPORTANCE_NONE);
    }

    static String noticeKind(JSONObject row) {
        JSONObject content = row == null ? null : row.optJSONObject("content");
        JSONObject refs = content == null ? null : content.optJSONObject("refs");
        String source = refs == null ? "" : refs.optString("source");
        if (!("tls_chat_direct".equals(source) || "qq_confirmed_proactive".equals(source))) return "reply";
        JSONObject notice = refs.optJSONObject("tls_notice");
        Object schema = notice == null ? null : notice.opt("schema");
        if (schema instanceof Number && ((Number) schema).doubleValue() == 1) {
            String kind = notice.optString("kind");
            if ("proactive".equals(kind) || "reminder".equals(kind)) return kind;
        }
        return "tls_message";
    }

    static String noticeTitle(String kind, String conversation) {
        String label = "reminder".equals(kind) ? "日程提醒" : "proactive".equals(kind) ? "主动消息"
                : "tls_message".equals(kind) ? "TLS 消息" : "新回复";
        return label + " · " + conversation;
    }

    private Notification ongoing(Watch selected) {
        Intent stop = new Intent(this, ReplyWatchService.class).setAction(STOP);
        PendingIntent stopAction = PendingIntent.getService(this, WATCH_NOTIFICATION, stop,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        Notification.Builder note = new Notification.Builder(this, WATCH_CHANNEL)
                .setSmallIcon(R.drawable.ic_notification).setContentTitle(BuildConfig.APP_NAME + " 回复监控")
                .setContentText(watches.isEmpty() ? "正在连接已启用的聊天…" : "正在留意 " + watches.size() + " 个聊天，各自每30秒读取一次")
                .setOngoing(true).setOnlyAlertOnce(true).setCategory(Notification.CATEGORY_SERVICE)
                .addAction(new Notification.Action.Builder(android.R.drawable.ic_media_pause, "停止监控", stopAction).build());
        if (selected != null) note.setContentIntent(PendingIntent.getActivity(this, WATCH_NOTIFICATION,
                openIntent(this, selected), PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE));
        return note.build();
    }

    private static int replyId(Watch selected) { return 4400 + (selected.scope.hashCode() & 0x3fff); }

    private static String preview(JSONObject row) {
        if (row == null) return "";
        JSONArray parts = row.optJSONArray("tls_parts");
        JSONObject content = row.optJSONObject("content");
        if ((parts == null || parts.length() == 0) && content != null) parts = content.optJSONArray("message");
        StringBuilder value = new StringBuilder();
        boolean media = false;
        boolean textMessage = false;
        if (parts != null) for (int index = 0; index < parts.length(); index++) {
            JSONObject part = parts.optJSONObject(index);
            if (part == null) continue;
            String type = part.optString("type");
            if ("plain".equals(type) || "speech".equals(type) || "action".equals(type)) {
                String fragment = part.optString("text").trim();
                if ("action".equals(type) && fragment.isEmpty()) fragment = part.optString("description").trim();
                if (!fragment.isEmpty()) textMessage = true;
                String readable = "plain".equals(type) ? readablePlain(fragment) : fragment;
                if (readable.isEmpty()) continue;
                if (value.length() > 0) value.append(' ');
                value.append("action".equals(type) ? "（" + readable + "）" : readable);
            } else if ("image".equals(type) || "file".equals(type) || "record".equals(type) || "video".equals(type)) {
                media = true;
            }
        }
        return text(value.toString(), media ? "收到新的图片、表情或附件" : textMessage ? "收到新的回复，打开查看" : "", 160);
    }

    private static String readablePlain(String input) {
        String value = input == null ? "" : input.trim();
        if (!(value.startsWith("{") || value.startsWith("```")) || !value.contains("\"tls_reply\"")) return value;
        // Old histories may contain the model protocol instead of tls_parts.
        // Render only its closed text schema; never show the protocol object.
        if (value.getBytes(StandardCharsets.UTF_8).length > 65536) return "";
        if (value.startsWith("```")) {
            int opening = value.indexOf('\n');
            if (opening < 0 || !value.endsWith("```")) return "";
            value = value.substring(opening + 1, value.length() - 3).trim();
        }
        try {
            JSONObject envelope = new JSONObject(value);
            JSONObject body = envelope.optJSONObject("tls_reply");
            Object schema = body == null ? null : body.opt("schema");
            JSONArray parts = body == null ? null : body.optJSONArray("parts");
            if (envelope.length() != 1 || body == null || body.length() != 2
                    || !(schema instanceof Integer || schema instanceof Long) || ((Number) schema).longValue() != 1
                    || parts == null || parts.length() == 0 || parts.length() > 16) return "";
            StringBuilder result = new StringBuilder();
            int total = 0;
            for (int index = 0; index < parts.length(); index++) {
                JSONObject part = parts.optJSONObject(index);
                if (part == null || part.length() != 2 || !(part.opt("text") instanceof String)) return "";
                String type = part.optString("type"), fragment = part.optString("text").trim();
                if (!("speech".equals(type) || "action".equals(type)) || fragment.isEmpty()) return "";
                total += fragment.length();
                if (total > 16000) return "";
                for (int offset = 0; offset < fragment.length(); offset++) {
                    char ch = fragment.charAt(offset);
                    if (ch < 32 && ch != '\n' && ch != '\r' && ch != '\t') return "";
                }
                if (result.length() > 0) result.append(' ');
                result.append("action".equals(type) ? "（" + fragment + "）" : fragment);
            }
            return result.toString();
        } catch (JSONException | StackOverflowError invalid) { return ""; }
    }

    private static String text(String value, String fallback, int limit) {
        String result = value == null ? "" : value.trim().replace('\r', ' ').replace('\n', ' ');
        if (result.isEmpty()) result = fallback;
        return result.length() > limit ? result.substring(0, limit) : result;
    }

    private static String read(InputStream stream) throws Exception {
        try (InputStream input = stream; ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[8192];
            int length;
            while ((length = input.read(buffer)) != -1) {
                if (output.size() + length > 8 * 1024 * 1024) throw new java.io.IOException("history_too_large");
                output.write(buffer, 0, length);
            }
            return new String(output.toByteArray(), StandardCharsets.UTF_8);
        }
    }

    private void cancelRead(Watch selected) {
        ScheduledFuture<?> task = selected.pending;
        if (task != null) task.cancel(false);
        HttpsURLConnection active = selected.connection;
        if (active != null) active.disconnect();
    }

    private void finish(String reason) {
        final long stoppingTicket;
        synchronized (ADMISSION) {
            stoppingTicket = ++admissionEpoch; startPending = false;
            SharedPreferences.Editor edit = metadata.edit().putBoolean("enabled", false).putBoolean("accounts_migrated", true);
            for (ReplyWatchAccounts.Record record : ReplyWatchAccounts.list(this))
                edit.putBoolean("paused_" + record.id, true).putString("stop_reason_" + record.id, reason);
            edit.apply();
            for (Watch selected : new ArrayList<>(watches.values())) removeWatch(selected, reason);
            running = false;
            clearPrivateNotices(this, reason);
            publish("stopped", reason, null, false, 0);
        }
        main.post(() -> {
            synchronized (ADMISSION) {
                if (stoppingTicket != admissionEpoch || !watches.isEmpty()) return;
                stopForeground(STOP_FOREGROUND_REMOVE); stopSelf();
            }
        });
    }

    private static boolean privateStop(String reason) {
        return "logged_out".equals(reason) || "server_changed".equals(reason)
                || "authentication_changed".equals(reason) || "login_expired".equals(reason) || "login_required".equals(reason);
    }

    private static void clearScopeNotices(Context context, String scope, String oldAuthScope, boolean identity) {
        cancelNotices(context, scope);
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        if (manager != null) cancelLegacyNotice(manager, oldAuthScope);
        if (identity) context.getSharedPreferences("asteria_chat_notification_identity", MODE_PRIVATE).edit().remove(scope).apply();
        if (Build.VERSION.SDK_INT >= 29) try {
            ShortcutManager shortcuts = context.getSystemService(ShortcutManager.class);
            if (shortcuts != null) {
                List<String> exact = Collections.singletonList(SHORTCUT_PREFIX + scope);
                shortcuts.disableShortcuts(exact);
                shortcuts.removeDynamicShortcuts(exact);
                if (Build.VERSION.SDK_INT >= 30) shortcuts.removeLongLivedShortcuts(exact);
            }
        } catch (RuntimeException unavailable) { /* The activity still validates the server, account and session. */ }
    }

    private static void clearPrivateNotices(Context context, String reason) {
        if (!privateStop(reason)) return;
        for (ReplyWatchAccounts.Record record : ReplyWatchAccounts.list(context))
            clearScopeNotices(context, record.id, authScope(record.server, record.token, record.session), true);
    }

    @Override public void onTimeout(int startId, int fgsType) { finish("system_time_limit"); }
    @Override public IBinder onBind(Intent intent) { return null; }
    @Override public void onDestroy() {
        synchronized (ADMISSION) {
            boolean interrupted = running;
            running = false;
            for (Watch selected : watches.values()) {
                cancelRead(selected);
                if (interrupted) rememberStop(selected, "service_destroyed");
            }
            watches.clear(); executor.shutdownNow();
            if (current == this) { current = null; latest = snapshot(this); }
        }
        super.onDestroy();
    }

    private void rememberStop(Watch selected, String reason) {
        if (selected == null || metadata == null) return;
        metadata.edit().putString("stop_reason_" + selected.scope, reason)
                .putLong("stop_at_" + selected.scope, System.currentTimeMillis()).apply();
    }
}
