package com.asteria.chat;

import android.app.NotificationManager;
import android.content.ComponentName;
import android.content.Context;
import android.media.MediaMetadata;
import android.media.session.MediaController;
import android.media.session.MediaSession;
import android.media.session.MediaSessionManager;
import android.media.session.PlaybackState;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.service.notification.NotificationListenerService;
import android.service.notification.StatusBarNotification;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.json.JSONObject;

/** Media-session metadata only. Ordinary notification contents are never inspected. */
public final class PerceptionMediaListener extends NotificationListenerService {
    private static final Object LOCK = new Object();
    private static final Handler MAIN = new Handler(Looper.getMainLooper());
    private static final int MAX_SESSIONS = 8;
    private static final Map<MediaSession.Token, Entry> ENTRIES = new LinkedHashMap<>();
    private static Context application;
    private static MediaSessionManager manager;
    private static MediaSessionManager.OnActiveSessionsChangedListener sessionsListener;
    private static long generation;
    private static boolean refreshQueued, overCapacity;

    private static final class Entry {
        final MediaController controller;
        final MediaSession.Token token;
        final String session = UUID.randomUUID().toString();
        final long epoch;
        final MediaController.Callback callback;
        JSONObject sample;
        String signature = "";

        Entry(MediaController value, long epoch) {
            controller = value; token = value.getSessionToken(); this.epoch = epoch;
            callback = new MediaController.Callback() {
                @Override public void onPlaybackStateChanged(PlaybackState state) {
                    try { observe(Entry.this, state, controller.getMetadata()); }
                    catch (RuntimeException unavailable) { invalidate(Entry.this); }
                }
                @Override public void onMetadataChanged(MediaMetadata metadata) {
                    try { observe(Entry.this, controller.getPlaybackState(), metadata); }
                    catch (RuntimeException unavailable) { invalidate(Entry.this); }
                }
                @Override public void onSessionDestroyed() {
                    Context context;
                    synchronized (LOCK) {
                        if (epoch != generation || ENTRIES.get(token) != Entry.this) return;
                        ENTRIES.remove(token); sample = null; context = application;
                    }
                    detach(Entry.this);
                    if (context != null) PhonePerceptionService.signalMediaChanged(context);
                }
            };
        }
    }

    public static boolean permissionGranted(Context context) {
        try {
            ComponentName component = new ComponentName(context, PerceptionMediaListener.class);
            if (Build.VERSION.SDK_INT >= 27) {
                NotificationManager notifications = context.getSystemService(NotificationManager.class);
                return notifications != null && notifications.isNotificationListenerAccessGranted(component);
            }
            String enabled = Settings.Secure.getString(context.getContentResolver(), "enabled_notification_listeners");
            if (enabled != null) for (String value : enabled.split(":"))
                if (component.equals(ComponentName.unflattenFromString(value))) return true;
        } catch (RuntimeException unavailable) { return false; }
        return false;
    }

    private static boolean allowed(Context context) {
        return context != null && PhonePerceptionService.musicEnabled(context) && permissionGranted(context);
    }

    /** Explicit collector ticks may refresh sessions; this creates no timer or worker. */
    public static void refresh(Context context) {
        final Context app = context.getApplicationContext();
        if (!allowed(app)) { clear(); return; }
        synchronized (LOCK) {
            if (refreshQueued) return;
            refreshQueued = true;
        }
        MAIN.post(() -> {
            synchronized (LOCK) { refreshQueued = false; }
            if (!allowed(app)) { clear(); return; }
            try {
                final MediaSessionManager selected = app.getSystemService(MediaSessionManager.class);
                if (selected == null) { clear(); return; }
                synchronized (LOCK) {
                    application = app;
                    if (manager != selected || sessionsListener == null) {
                        if (manager != null && sessionsListener != null)
                            manager.removeOnActiveSessionsChangedListener(sessionsListener);
                        manager = selected;
                        final long epoch = generation;
                        sessionsListener = controllers -> {
                            synchronized (LOCK) { if (generation != epoch || manager != selected) return; }
                            try { reconcile(app, controllers); }
                            catch (RuntimeException unavailable) { clear(); }
                        };
                        selected.addOnActiveSessionsChangedListener(sessionsListener,
                                new ComponentName(app, PerceptionMediaListener.class), MAIN);
                    }
                }
                reconcile(app, selected.getActiveSessions(new ComponentName(app, PerceptionMediaListener.class)));
            } catch (RuntimeException unavailable) { clear(); }
        });
    }

    private static void reconcile(Context context, List<MediaController> controllers) {
        if (!allowed(context)) { clear(); return; }
        if (controllers == null) controllers = new ArrayList<>();
        List<Entry> removed = new ArrayList<>(), selected = new ArrayList<>();
        synchronized (LOCK) {
            overCapacity = controllers.size() > MAX_SESSIONS;
            Map<MediaSession.Token, MediaController> active = new LinkedHashMap<>();
            for (MediaController controller : controllers) {
                if (active.size() == MAX_SESSIONS) break;
                if (controller != null) active.put(controller.getSessionToken(), controller);
            }
            for (Entry entry : ENTRIES.values()) if (!active.containsKey(entry.token)) removed.add(entry);
            for (Entry entry : removed) ENTRIES.remove(entry.token);
            for (Map.Entry<MediaSession.Token, MediaController> item : active.entrySet()) {
                Entry entry = ENTRIES.get(item.getKey());
                if (entry == null) {
                    entry = new Entry(item.getValue(), generation);
                    ENTRIES.put(item.getKey(), entry);
                    entry.controller.registerCallback(entry.callback, MAIN);
                }
                selected.add(entry);
            }
        }
        for (Entry entry : removed) detach(entry);
        for (Entry entry : selected) {
            try { observe(entry, entry.controller.getPlaybackState(), entry.controller.getMetadata()); }
            catch (RuntimeException unavailable) {
                synchronized (LOCK) { if (ENTRIES.get(entry.token) == entry) entry.sample = null; }
            }
        }
    }

    private static void observe(Entry entry, PlaybackState playback, MediaMetadata metadata) {
        Context context;
        synchronized (LOCK) {
            if (entry.epoch != generation || ENTRIES.get(entry.token) != entry) return;
            context = application;
        }
        if (!allowed(context)) { clear(); return; }
        if (playback == null) {
            synchronized (LOCK) { if (ENTRIES.get(entry.token) == entry) entry.sample = null; }
            return;
        }
        try {
            String pkg = entry.controller.getPackageName();
            if (pkg == null || pkg.length() > 160 || !pkg.matches("[A-Za-z0-9_]+(?:\\.[A-Za-z0-9_]+)+")) return;
            String state;
            switch (playback.getState()) {
                case PlaybackState.STATE_PLAYING: state = "playing"; break;
                case PlaybackState.STATE_PAUSED: state = "paused"; break;
                case PlaybackState.STATE_STOPPED:
                case PlaybackState.STATE_NONE: state = "stopped"; break;
                case PlaybackState.STATE_BUFFERING:
                case PlaybackState.STATE_CONNECTING: state = "buffering"; break;
                default: state = "unknown";
            }
            JSONObject record = new JSONObject().put("schema_version", 1).put("source", "media_session")
                    .put("state", state).put("playing", "playing".equals(state)).put("package", pkg)
                    .put("session_id", entry.session).put("observed_at", System.currentTimeMillis() / 1000.0);
            if (metadata != null) {
                putText(record, "title", metadata.getText(MediaMetadata.METADATA_KEY_TITLE));
                putText(record, "artist", metadata.getText(MediaMetadata.METADATA_KEY_ARTIST));
                putText(record, "album", metadata.getText(MediaMetadata.METADATA_KEY_ALBUM));
                putText(record, "track_id", metadata.getText(MediaMetadata.METADATA_KEY_MEDIA_ID));
                long duration = metadata.getLong(MediaMetadata.METADATA_KEY_DURATION);
                if (duration > 0 && duration <= 7L * 86400000L) record.put("duration_ms", duration);
            }
            long progress = playback.getPosition();
            if (progress >= 0 && progress <= 7L * 86400000L
                    && (!record.has("duration_ms") || progress <= record.getLong("duration_ms")))
                record.put("progress_ms", progress);
            float speed = playback.getPlaybackSpeed();
            if (!Float.isNaN(speed) && !Float.isInfinite(speed) && speed >= 0 && speed <= 4)
                record.put("playback_speed", (double) speed);
            String signature = pkg + "\n" + state + "\n" + record.optString("track_id") + "\n"
                    + record.optString("title") + "\n" + record.optString("artist");
            boolean changed;
            synchronized (LOCK) {
                if (entry.epoch != generation || ENTRIES.get(entry.token) != entry || !allowed(context)) return;
                changed = !signature.equals(entry.signature); entry.signature = signature; entry.sample = record;
            }
            if (changed) PhonePerceptionService.signalMediaChanged(context);
        } catch (Exception unavailable) {
            synchronized (LOCK) { if (ENTRIES.get(entry.token) == entry) entry.sample = null; }
        }
    }

    private static void putText(JSONObject target, String key, CharSequence value) throws Exception {
        if (value == null) return;
        StringBuilder safe = new StringBuilder();
        for (int index = 0; index < value.length() && index < 512 && safe.length() < 120; index++) {
            char c = value.charAt(index);
            safe.append(c < 32 || c == 127 || c == '<' || c == '>' ? ' ' : c);
        }
        String result = safe.toString().trim();
        if (!result.isEmpty()) target.put(key, result);
    }

    /** A detached copy; two different playing tracks remain ambiguous. */
    public static JSONObject snapshot(Context context) {
        if (!allowed(context)) { clear(); return null; }
        synchronized (LOCK) {
            if (overCapacity) return null;
            JSONObject selected = null;
            String playingIdentity = null;
            boolean hasPlaying = false;
            for (Entry entry : ENTRIES.values()) {
                JSONObject value = entry.sample;
                if (value == null) continue;
                boolean playing = value.optBoolean("playing");
                if (playing) {
                    String identity = value.optString("package") + "\n" + value.optString("track_id")
                            + "\n" + value.optString("title") + "\n" + value.optString("artist");
                    if (playingIdentity != null && !playingIdentity.equals(identity)) return null;
                    playingIdentity = identity;
                }
                if (selected == null || playing && !hasPlaying || playing == hasPlaying
                        && value.optDouble("observed_at") > selected.optDouble("observed_at")) {
                    selected = value; hasPlaying = playing;
                }
            }
            if (selected == null || !allowed(context)) return null;
            try { return new JSONObject(selected.toString()); }
            catch (Exception unavailable) { return null; }
        }
    }

    /** Invalidates data immediately; stale callbacks cannot repopulate the cache. */
    public static void clear() {
        final List<Entry> previous;
        final MediaSessionManager oldManager;
        final MediaSessionManager.OnActiveSessionsChangedListener oldListener;
        synchronized (LOCK) {
            generation++; previous = new ArrayList<>(ENTRIES.values()); ENTRIES.clear();
            oldManager = manager; oldListener = sessionsListener;
            manager = null; sessionsListener = null; application = null; overCapacity = false;
        }
        MAIN.post(() -> {
            if (oldManager != null && oldListener != null) {
                try { oldManager.removeOnActiveSessionsChangedListener(oldListener); }
                catch (RuntimeException ignored) { }
            }
            for (Entry entry : previous) detach(entry);
        });
    }

    private static void detach(Entry entry) {
        try { entry.controller.unregisterCallback(entry.callback); }
        catch (RuntimeException ignored) { }
    }

    private static void invalidate(Entry entry) {
        synchronized (LOCK) { if (ENTRIES.get(entry.token) == entry) entry.sample = null; }
    }

    @Override public void onListenerConnected() { super.onListenerConnected(); refresh(this); }
    @Override public void onListenerDisconnected() { clear(); super.onListenerDisconnected(); }
    @Override public void onNotificationPosted(StatusBarNotification notification) { refresh(this); }
    @Override public void onNotificationRemoved(StatusBarNotification notification) { refresh(this); }
    @Override public void onDestroy() { clear(); super.onDestroy(); }
}
