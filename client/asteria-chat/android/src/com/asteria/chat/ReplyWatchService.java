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
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;
import javax.net.ssl.HttpsURLConnection;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/** Explicit foreground-service polling while the app is hidden. This is not push. */
public final class ReplyWatchService extends Service {
    private static final String START = "com.asteria.chat.REPLY_WATCH_START";
    private static final String STOP = "com.asteria.chat.REPLY_WATCH_STOP";
    private static final String WATCH_CHANNEL = "asteria-chat-reply-watch";
    private static final String REPLY_CHANNEL = "asteria-chat-replies";
    private static final int WATCH_NOTIFICATION = 4300;
    private static final int MAX_NOTICE_MESSAGES = 8;
    private static final String SHORTCUT_PREFIX = "asteria-chat.reply.";
    private static final long POLL_MS = 30000;
    private static final Object NETWORK_GATE = new Object();
    private static final Object ADMISSION = new Object();
    private static long admissionEpoch;
    private static long lastNetworkStarted = -POLL_MS;
    private static volatile ReplyWatchService current;
    private static volatile boolean appForeground;
    private static volatile String latest = "{\"state\":\"stopped\",\"running\":false,\"verified_session\":false}";
    private static volatile Observer observer;

    interface Observer { void changed(String state); }

    private final Handler main = new Handler(Looper.getMainLooper());
    private final ScheduledExecutorService executor = Executors.newSingleThreadScheduledExecutor(runnable -> {
        Thread thread = new Thread(runnable, "asteria-chat-reply-watch");
        thread.setDaemon(true);
        return thread;
    });
    private volatile Watch watch;
    private volatile boolean running;
    private volatile HttpsURLConnection connection;
    private ScheduledFuture<?> pending;
    private SharedPreferences metadata;

    private static final class Watch {
        final String server, token, session, title, scope, baseline;
        volatile boolean initialized, verified;
        volatile String cursor = "";
        final List<NoticeMessage> notices = new ArrayList<>();
        int failures;
        Watch(String server, String token, String session, String title, String baseline) {
            this.server = server; this.token = token; this.session = session;
            this.title = text(title, BuildConfig.APP_NAME, 40); this.baseline = baseline == null ? "" : baseline;
            scope = scope(server, token, session);
        }
    }

    private static final class NoticeMessage {
        final String id, text;
        final long timestamp;
        NoticeMessage(String id, String text, long timestamp) {
            this.id = id; this.text = text; this.timestamp = timestamp;
        }
    }

    static String snapshot() { return latest; }
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
    static void setAppForeground(boolean value) { appForeground = value; }

    private static void publish(String state, String reason, Watch value, boolean running, long nextPoll) {
        JSONObject record = new JSONObject();
        try {
            record.put("state", state); record.put("running", running);
            record.put("verified_session", value != null && value.verified);
            record.put("session_id", value == null ? JSONObject.NULL : value.session);
            record.put("title", value == null ? JSONObject.NULL : value.title);
            record.put("reason", reason == null ? JSONObject.NULL : reason);
            record.put("poll_interval_seconds", 30);
            record.put("next_poll_seconds", Math.max(0, nextPoll / 1000));
            record.put("server_push", false); record.put("requires_explicit_enable", true);
            record.put("system_restart_recovery", true); record.put("system_time_limit_applies", true);
        } catch (JSONException invalid) { return; }
        latest = record.toString();
        Observer valueObserver = observer;
        if (valueObserver != null) valueObserver.changed(latest);
    }

    static boolean acknowledge(String server, String token, String session, String messageId) {
        if (!appForeground || messageId == null || messageId.isEmpty() || messageId.length() > 160) return false;
        String normalized = ApiPolicy.server(server);
        AttachmentPolicy.session(session);
        if (!ApiPolicy.jwt(token)) return false;
        synchronized (ADMISSION) {
            ReplyWatchService active = current;
            Watch selected = active == null ? null : active.watch;
            if (!appForeground || active == null || selected == null || !active.current(selected)
                    || !selected.scope.equals(scope(normalized, token, session))) return false;
            if (!messageId.equals(selected.cursor)) active.remember(selected, messageId);
            selected.notices.clear();
            selected.initialized = true;
            return true;
        }
    }

    static String start(Context context, String server, String token, String session, String title, String baseline) {
        String normalized = ApiPolicy.server(server);
        AttachmentPolicy.session(session);
        if (!ApiPolicy.jwt(token)) throw new IllegalStateException("saved_login_required");
        ReplyWatchService active = current;
        if (active != null && active.running && active.watch != null
                && active.watch.scope.equals(scope(normalized, token, session))) return latest;
        Watch selected = new Watch(normalized, token, session, title, baseline);
        synchronized (ADMISSION) {
            long ticket = ++admissionEpoch;
            if (active != null) { active.running = false; active.cancelRead(); }
            Intent command = new Intent(context, ReplyWatchService.class).setAction(START)
                    .putExtra("server", normalized).putExtra("session_id", session)
                    .putExtra("title", selected.title).putExtra("baseline", selected.baseline)
                    .putExtra("auth_scope", selected.scope).putExtra("admission_epoch", ticket);
            publish("starting", null, selected, false, 0);
            try { context.startForegroundService(command); }
            catch (RuntimeException unavailable) { publish("stopped", "foreground_start_not_allowed", selected, false, 0); }
        }
        return latest;
    }

    static void stop(Context context, String reason) {
        synchronized (ADMISSION) { admissionEpoch++; }
        context.getSharedPreferences("asteria_chat_reply_watch", MODE_PRIVATE).edit().putBoolean("enabled", false).apply();
        clearPrivateNotices(context, reason);
        ReplyWatchService active = current;
        if (active != null) active.finish(reason);
        else {
            context.stopService(new Intent(context, ReplyWatchService.class));
            publish("stopped", reason, null, false, 0);
        }
    }

    static String notificationSession(Intent intent, String server, String token) {
        if (intent == null || !ApiPolicy.jwt(token)) return null;
        String session = intent.getStringExtra("session_id");
        try {
            AttachmentPolicy.session(session);
            return scope(server, token, session).equals(intent.getStringExtra("reply_watch_scope")) ? session : null;
        } catch (RuntimeException invalid) { return null; }
    }

    private static Intent openIntent(Context context, Watch selected) {
        return new Intent(context, MainActivity.class)
                .setData(Uri.parse("asteria-chat://reply/" + selected.scope))
                .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP | Intent.FLAG_ACTIVITY_CLEAR_TOP)
                .putExtra("session_id", selected.session).putExtra("reply_watch_scope", selected.scope);
    }

    private static String scope(String server, String token, String session) {
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
        if (intent == null) {
            try { intent = restoreCommand(); }
            catch (RuntimeException unavailable) { finish("restart_registration_unavailable"); return START_NOT_STICKY; }
            if (intent == null) { finish("not_enabled"); return START_NOT_STICKY; }
        }
        if (STOP.equals(intent.getAction())) { finish("user_stopped"); return START_NOT_STICKY; }
        if (!START.equals(intent.getAction())) { finish("invalid_start"); return START_NOT_STICKY; }
        long ticket = intent.getLongExtra("admission_epoch", -1);
        synchronized (ADMISSION) {
            if (ticket != admissionEpoch) { stopSelf(startId); return START_NOT_STICKY; }
        }
        try {
            // A visible foreground notification is posted before vault or HTTP work.
            Notification initial = ongoing(null);
            if (Build.VERSION.SDK_INT >= 29) startForeground(WATCH_NOTIFICATION, initial, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC);
            else startForeground(WATCH_NOTIFICATION, initial);
            if (!notificationsAllowed()) { finish("notification_permission"); return START_NOT_STICKY; }
            TokenVault vault = new TokenVault(this);
            String server = ApiPolicy.server(intent.getStringExtra("server"));
            if (!server.equals(vault.server())) { finish("authentication_changed"); return START_NOT_STICKY; }
            String token = vault.load(server);
            String session = AttachmentPolicy.session(intent.getStringExtra("session_id"));
            if (!ApiPolicy.jwt(token) || !scope(server, token, session).equals(intent.getStringExtra("auth_scope"))) {
                finish("authentication_changed"); return START_NOT_STICKY;
            }
            cancelRead();
            Watch selected = new Watch(server, token, session, intent.getStringExtra("title"), intent.getStringExtra("baseline"));
            synchronized (ADMISSION) {
                if (ticket != admissionEpoch) { stopSelf(startId); return START_NOT_STICKY; }
                watch = selected; running = true;
                metadata.edit().putBoolean("enabled", true)
                        .putString("registered_server", selected.server).putString("registered_session", selected.session)
                        .putString("registered_title", selected.title).putString("registered_baseline", selected.baseline)
                        .putString("registered_auth_scope", selected.scope).apply();
                publish("starting", null, selected, true, 0);
            }
            schedule(selected, nextAllowedDelay());
        } catch (RuntimeException invalid) { finish("watch_start_unavailable"); }
        return running ? START_STICKY : START_NOT_STICKY;
    }

    private Intent restoreCommand() {
        // Only restore a monitor explicitly enabled by the user. The token
        // remains in TokenVault; metadata contains no password or JWT.
        if (!metadata.getBoolean("enabled", false)) return null;
        TokenVault vault = new TokenVault(this);
        String server = ApiPolicy.server(metadata.getString("registered_server", ""));
        String session = AttachmentPolicy.session(metadata.getString("registered_session", ""));
        String token = vault.load(server);
        if (!server.equals(vault.server()) || !ApiPolicy.jwt(token)
                || !scope(server, token, session).equals(metadata.getString("registered_auth_scope", ""))) return null;
        synchronized (ADMISSION) {
            return new Intent(this, ReplyWatchService.class).setAction(START)
                    .putExtra("server", server).putExtra("session_id", session)
                    .putExtra("title", metadata.getString("registered_title", BuildConfig.APP_NAME))
                    .putExtra("baseline", "").putExtra("auth_scope", scope(server, token, session))
                    .putExtra("admission_epoch", ++admissionEpoch);
        }
    }

    private long nextAllowedDelay() {
        synchronized (NETWORK_GATE) { return Math.max(0, POLL_MS - (SystemClock.elapsedRealtime() - lastNetworkStarted)); }
    }

    private void schedule(Watch selected, long delay) {
        if (!current(selected)) return;
        try { pending = executor.schedule(() -> poll(selected), Math.max(0, delay), TimeUnit.MILLISECONDS); }
        catch (RuntimeException stopped) { finishWatch(selected, "watch_stopped"); }
    }

    private boolean current(Watch selected) { return running && watch == selected && current == this; }

    private void finishWatch(Watch selected, String reason) {
        synchronized (ADMISSION) { if (current(selected)) finish(reason); }
    }

    private void updateWatch(Watch selected, String state, String reason, long delay) {
        synchronized (ADMISSION) { if (current(selected)) publish(state, reason, selected, true, delay); }
    }

    private void poll(Watch selected) {
        if (!current(selected)) return;
        if (!notificationsAllowed()) { finishWatch(selected, "notification_permission"); return; }
        // The visible page owns its one history coordinator. Do not create a
        // second foreground read or advance a cursor for content it has not read.
        if (appForeground) {
            updateWatch(selected, "running", "foreground_ui_owns_reads", POLL_MS);
            schedule(selected, POLL_MS);
            return;
        }
        synchronized (NETWORK_GATE) {
            long delay = POLL_MS - (SystemClock.elapsedRealtime() - lastNetworkStarted);
            if (delay > 0) { schedule(selected, delay); return; }
            if (!current(selected)) return;
            lastNetworkStarted = SystemClock.elapsedRealtime();
        }
        HttpsURLConnection request = null;
        long delay = POLL_MS;
        try {
            String path = ApiPolicy.requestPath("/chat/history?session_id=" + URLEncoder.encode(selected.session, "UTF-8"));
            request = (HttpsURLConnection) new URL(selected.server + path).openConnection();
            connection = request;
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
                finishWatch(selected, status == 401 ? "login_expired" : "session_unavailable"); return;
            }
            if (status < 200 || status >= 300) throw new java.io.IOException("history_unavailable");
            JSONObject envelope = new JSONObject(read(request.getInputStream()));
            if (envelope.has("status") && !"ok".equals(envelope.optString("status")))
                throw new java.io.IOException("history_not_successful");
            JSONObject data = envelope.optJSONObject("data");
            if (data == null) data = envelope;
            JSONArray history = data.optJSONArray("history");
            if (history == null) throw new java.io.IOException("history_shape_unavailable");
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
            if (appForeground) { updateWatch(selected, "running", "foreground_ui_owns_reads", delay); return; }
            reconcile(selected, assistants);
            if (!current(selected)) return;
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
            updateWatch(selected, "reconnecting", "network_or_history_unavailable", delay);
        } finally {
            if (request != null) request.disconnect();
            if (connection == request) connection = null;
            if (current(selected)) schedule(selected, delay);
        }
    }

    private void reconcile(Watch selected, List<JSONObject> rows) {
        String newest = rows.isEmpty() ? "" : String.valueOf(rows.get(rows.size() - 1).opt("id"));
        if (!selected.initialized) {
            selected.initialized = true;
            if (!selected.baseline.isEmpty()) selected.cursor = selected.baseline;
            else if (selected.scope.equals(metadata.getString("scope", ""))) selected.cursor = metadata.getString("last_seen_id", "");
            else { remember(selected, newest); return; }
        }
        int anchor = -1;
        if (!selected.cursor.isEmpty()) {
            for (int index = 0; index < rows.size(); index++)
                if (selected.cursor.equals(String.valueOf(rows.get(index).opt("id")))) anchor = index;
            // The saved cursor fell outside the server's bounded history; do
            // not turn unknown older records into a batch of fresh alerts.
            if (anchor < 0) { remember(selected, newest); return; }
        }
        if (rows.size() - 1 <= anchor || rows.isEmpty()) return;
        if (!current(selected)) return;
        if (appForeground) return;
        if (!notificationsAllowed()) { finishWatch(selected, "notification_permission"); return; }
        NotificationManager manager = getSystemService(NotificationManager.class);
        if (manager == null) throw new IllegalStateException("notification_manager_unavailable");
        List<NoticeMessage> incoming = newNoticeMessages(rows, anchor, System.currentTimeMillis());
        synchronized (ADMISSION) {
            if (!current(selected) || appForeground) return;
            // Empty SDK save rows still advance the receipt cursor, but do not
            // become a fabricated new reply or replace a meaningful preview.
            if (!incoming.isEmpty()) {
                mergeNoticeMessages(selected.notices, incoming);
                String kind = "reply";
                String lastNoticeId = incoming.get(incoming.size() - 1).id;
                for (int index = rows.size() - 1; index > anchor; index--)
                    if (lastNoticeId.equals(String.valueOf(rows.get(index).opt("id")))) { kind = noticeKind(rows.get(index)); break; }
                manager.notify(replyId(selected), conversationNotification(selected, kind));
            }
            remember(selected, newest);
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

    private Notification conversationNotification(Watch selected, String kind) {
        Notification.MessagingStyle style;
        if (Build.VERSION.SDK_INT >= 28) {
            Person self = new Person.Builder().setName("我").build();
            Person texas = new Person.Builder().setName(selected.title).setKey(selected.scope)
                    .setUri("asteria-chat://person/" + selected.scope).setBot(true).build();
            style = new Notification.MessagingStyle(self).setGroupConversation(false);
            for (NoticeMessage value : selected.notices)
                style.addMessage(new Notification.MessagingStyle.Message(value.text, value.timestamp, texas));
        } else {
            style = new Notification.MessagingStyle("我");
            for (NoticeMessage value : selected.notices)
                style.addMessage(value.text, value.timestamp, selected.title);
        }
        style.setConversationTitle(selected.title);
        PendingIntent open = PendingIntent.getActivity(this, replyId(selected), openIntent(this, selected),
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        String latestPreview = selected.notices.get(selected.notices.size() - 1).text;
        Notification.Builder note = new Notification.Builder(this, REPLY_CHANNEL)
                .setSmallIcon(R.drawable.ic_notification)
                .setContentTitle(noticeTitle(kind, selected.title)).setContentText(latestPreview)
                .setCategory("reminder".equals(kind) ? Notification.CATEGORY_REMINDER : Notification.CATEGORY_MESSAGE)
                .setStyle(style).setVisibility(Notification.VISIBILITY_PRIVATE)
                .setAutoCancel(true).setContentIntent(open);
        if (publishConversationShortcut(selected)) note.setShortcutId(SHORTCUT_PREFIX + selected.scope);
        return note.build();
    }

    private boolean publishConversationShortcut(Watch selected) {
        if (Build.VERSION.SDK_INT < 29) return false;
        try {
            ShortcutManager shortcuts = getSystemService(ShortcutManager.class);
            if (shortcuts == null) return false;
            Person texas = new Person.Builder().setName(selected.title).setKey(selected.scope).setBot(true).build();
            ShortcutInfo shortcut = new ShortcutInfo.Builder(this, SHORTCUT_PREFIX + selected.scope)
                    .setShortLabel(selected.title).setLongLabel(selected.title)
                    .setIntent(openIntent(this, selected).setAction(Intent.ACTION_VIEW))
                    .setPersons(new Person[] { texas }).setLongLived(true)
                    .setCategories(Collections.singleton("android.shortcut.conversation")).build();
            if (Build.VERSION.SDK_INT >= 30) { shortcuts.pushDynamicShortcut(shortcut); return true; }
            return shortcuts.addDynamicShortcuts(Collections.singletonList(shortcut));
        } catch (RuntimeException unavailable) {
            // A launcher limitation must not suppress the ordinary reply notification.
            return false;
        }
    }

    private void remember(Watch selected, String id) {
        synchronized (ADMISSION) {
            if (!current(selected)) return;
            if (!metadata.edit().putString("scope", selected.scope).putString("last_seen_id", id).commit())
                throw new IllegalStateException("watch_cursor_not_saved");
            selected.cursor = id;
        }
    }

    private boolean notificationsAllowed() {
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
                .setContentText(selected == null ? "正在连接当前会话…" : "正在留意“" + selected.title + "”的新回复，每30秒读取一次")
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
                if (!part.optString("text").trim().isEmpty()) textMessage = true;
                String readable = "plain".equals(type) ? readablePlain(part.optString("text")) : part.optString("text").trim();
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

    private void cancelRead() {
        ScheduledFuture<?> task = pending;
        if (task != null) task.cancel(false);
        HttpsURLConnection active = connection;
        if (active != null) active.disconnect();
    }

    private void finish(String reason) {
        final Watch previous;
        final long stoppingTicket;
        synchronized (ADMISSION) {
            stoppingTicket = ++admissionEpoch;
            previous = watch;
            running = false; watch = null;
            metadata.edit().putBoolean("enabled", false).apply();
            cancelRead();
            clearPrivateNotices(this, reason);
            publish("stopped", reason, previous, false, 0);
        }
        main.post(() -> {
            synchronized (ADMISSION) {
                if (stoppingTicket != admissionEpoch) return;
                stopForeground(STOP_FOREGROUND_REMOVE); stopSelf();
            }
        });
    }

    private static void clearPrivateNotices(Context context, String reason) {
        if (!("logged_out".equals(reason) || "server_changed".equals(reason)
                || "authentication_changed".equals(reason) || "login_expired".equals(reason)
                || "login_required".equals(reason))) return;
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        if (manager != null) manager.cancelAll();
        if (Build.VERSION.SDK_INT >= 29) try {
            ShortcutManager shortcuts = context.getSystemService(ShortcutManager.class);
            if (shortcuts != null) {
                List<String> owned = new ArrayList<>();
                List<ShortcutInfo> candidates = Build.VERSION.SDK_INT >= 30
                        ? shortcuts.getShortcuts(ShortcutManager.FLAG_MATCH_DYNAMIC | ShortcutManager.FLAG_MATCH_PINNED | ShortcutManager.FLAG_MATCH_CACHED)
                        : new ArrayList<>(shortcuts.getDynamicShortcuts());
                if (Build.VERSION.SDK_INT < 30) candidates.addAll(shortcuts.getPinnedShortcuts());
                for (ShortcutInfo shortcut : candidates)
                    if (shortcut.getId().startsWith(SHORTCUT_PREFIX) && !owned.contains(shortcut.getId())) owned.add(shortcut.getId());
                // These shortcuts can be cached by the system. Disable them
                // before removal so a logged-out chat cannot remain actionable.
                if (!owned.isEmpty()) {
                    shortcuts.disableShortcuts(owned);
                    shortcuts.removeDynamicShortcuts(owned);
                    if (Build.VERSION.SDK_INT >= 30) shortcuts.removeLongLivedShortcuts(owned);
                }
            }
        } catch (RuntimeException unavailable) { /* The activity still validates the current auth scope. */ }
    }

    @Override public void onTimeout(int startId, int fgsType) { finish("system_time_limit"); }
    @Override public IBinder onBind(Intent intent) { return null; }
    @Override public void onDestroy() {
        Watch previous = watch;
        boolean interrupted = running;
        running = false; watch = null;
        cancelRead(); executor.shutdownNow();
        if (current == this) {
            current = null;
            if (interrupted) publish("stopped", "service_destroyed", previous, false, 0);
        }
        super.onDestroy();
    }
}
