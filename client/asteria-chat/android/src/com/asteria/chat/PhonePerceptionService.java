package com.asteria.chat;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.SystemClock;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Iterator;
import java.util.UUID;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;
import javax.net.ssl.HttpsURLConnection;
import org.json.JSONObject;

/** Explicit, revocable PPB-compatible collection through this app's existing authenticated server. */
public final class PhonePerceptionService extends Service {
    private static final String PREFS = "asteria_chat_perception";
    private static final String START = "com.asteria.chat.PERCEPTION_START";
    private static final String STOP = "com.asteria.chat.PERCEPTION_STOP";
    private static final String CHANNEL = "asteria-chat-phone-perception";
    private static final int NOTICE = 4600;
    private static final long FAST_MS = 15000L, BASIC_MS = 60000L;
    private static final Object GATE = new Object();
    private static long epoch;
    private static volatile PhonePerceptionService current;
    private static String state = "stopped", error;
    private static int httpStatus;
    private static double lastReportAt;
    private static double acceptedReportAt;
    private static String acceptedEventId;
    private static String acceptedServer, acceptedSession, acceptedInstallation;

    private final Handler main = new Handler(Looper.getMainLooper());
    private final ScheduledExecutorService executor = Executors.newSingleThreadScheduledExecutor(runnable -> {
        Thread thread = new Thread(runnable, "asteria-chat-phone-perception");
        thread.setDaemon(true);
        return thread;
    });
    private volatile Registration registration;
    private volatile boolean running;
    private volatile HttpsURLConnection connection;
    private ScheduledFuture<?> pending;
    private boolean inFlight, urgent, receiverRegistered;
    private SharedPreferences metadata;

    private static final class Sections {
        final boolean basic, app, music;
        Sections(JSONObject value) {
            if (value == null || value.length() != 3) throw new IllegalArgumentException("sections_required");
            for (Iterator<String> keys = value.keys(); keys.hasNext();) {
                String key = keys.next();
                if (!("basic".equals(key) || "app".equals(key) || "music".equals(key))
                        || !(value.opt(key) instanceof Boolean)) throw new IllegalArgumentException("invalid_sections");
            }
            basic = value.optBoolean("basic", false); app = value.optBoolean("app", false); music = value.optBoolean("music", false);
        }
        boolean any() { return basic || app || music; }
        boolean same(Sections other) { return basic == other.basic && app == other.app && music == other.music; }
        JSONObject json() {
            JSONObject value = new JSONObject();
            put(value, "basic", basic); put(value, "app", app); put(value, "music", music);
            return value;
        }
    }

    private static final class Registration {
        final String server, session, installation;
        final Sections sections;
        final long ticket;
        volatile boolean verified;
        String device, authentication;
        long lastStarted = -FAST_MS, lastBasic = -BASIC_MS;
        Registration(String server, String session, String installation, Sections sections, long ticket) {
            this.server = server; this.session = session; this.installation = installation;
            this.sections = sections; this.ticket = ticket;
        }
    }

    private static final class Rejected extends Exception {
        final String reason;
        Rejected(String reason) { this.reason = reason; }
    }

    public static String installationId(Context context) {
        synchronized (GATE) {
            SharedPreferences prefs = context.getApplicationContext().getSharedPreferences(PREFS, MODE_PRIVATE);
            String existing = prefs.getString("installation_id", "");
            if (existing != null && existing.matches("[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"))
                return existing;
            String created = UUID.randomUUID().toString();
            if (!prefs.edit().putString("installation_id", created).commit())
                throw new IllegalStateException("installation_not_saved");
            return created;
        }
    }

    /** Called only from the app's explicit enable action; no login or enrollment is performed here. */
    public static String start(Context context, String server, String session, JSONObject values) {
        return start(context, server, session, values, -1);
    }

    static long admissionGeneration() {
        synchronized (GATE) { return epoch; }
    }

    static String start(Context context, String server, String session, JSONObject values, long expectedGeneration) {
        Context app = context.getApplicationContext();
        String normalized = ApiPolicy.server(server);
        String selected = AttachmentPolicy.session(session);
        Sections sections = new Sections(values);
        if (!sections.any()) { stop(app, "sections_disabled"); return snapshot(app); }
        if (!normalized.equals(new TokenVault(app).server())) throw new IllegalStateException("server_changed");
        String installation = installationId(app);
        if (!notificationsAllowed(app)) { stop(app, "notification_permission"); return snapshot(app); }
        synchronized (GATE) {
            // This also observes stop actions from the notification or another Activity instance.
            if (expectedGeneration >= 0 && expectedGeneration != epoch) {
                try {
                    JSONObject cancelled = new JSONObject(snapshot(app));
                    put(cancelled, "start_cancelled", true); put(cancelled, "reason", "request_superseded");
                    return cancelled.toString();
                } catch (Exception unavailable) { throw new IllegalStateException("cancelled_snapshot_unavailable"); }
            }
            PhonePerceptionService active = current;
            Registration previous = active == null ? null : active.registration;
            if (active != null && active.running && previous != null && previous.server.equals(normalized)
                    && previous.session.equals(selected) && previous.sections.same(sections)) return snapshot(app);
            SharedPreferences prefs = app.getSharedPreferences(PREFS, MODE_PRIVATE);
            if (!prefs.edit().putBoolean("enabled", true).putString("server", normalized).putString("session_id", selected)
                    .putBoolean("basic", sections.basic).putBoolean("app", sections.app).putBoolean("music", sections.music).commit())
                throw new IllegalStateException("perception_settings_not_saved");
            long ticket = ++epoch;
            if (active != null) { active.running = false; active.cancelPending(); }
            state = "starting"; error = null; httpStatus = 0;
            Intent command = new Intent(app, PhonePerceptionService.class).setAction(START)
                    .putExtra("server", normalized).putExtra("session_id", selected)
                    .putExtra("installation_id", installation).putExtra("sections", sections.json().toString())
                    .putExtra("admission_epoch", ticket);
            try { app.startForegroundService(command); }
            catch (RuntimeException denied) {
                prefs.edit().putBoolean("enabled", false).commit();
                state = "stopped"; error = "foreground_start_not_allowed";
            }
        }
        return snapshot(app);
    }

    public static void stop(Context context, String reason) {
        Context app = context.getApplicationContext();
        PhonePerceptionService active;
        String code = reasonCode(reason);
        synchronized (GATE) {
            ++epoch;
            app.getSharedPreferences(PREFS, MODE_PRIVATE).edit().putBoolean("enabled", false).commit();
            state = "stopped"; error = code;
            invalidateAcceptedIdentity(code);
            active = current;
        }
        if (active != null) active.finish(null, code);
        else app.stopService(new Intent(app, PhonePerceptionService.class));
        PerceptionMediaListener.clear();
    }

    public static String snapshot(Context context) {
        Context app = context.getApplicationContext();
        JSONObject out = new JSONObject(), permissions = new JSONObject(), sections = new JSONObject();
        SharedPreferences prefs = app.getSharedPreferences(PREFS, MODE_PRIVATE);
        String installation = installationId(app);
        put(out, "installation_id", installation);
        put(permissions, "notifications", notificationsAllowed(app));
        put(permissions, "usage", PhonePerceptionCollector.usagePermissionGranted(app));
        put(permissions, "music", PerceptionMediaListener.permissionGranted(app));
        synchronized (GATE) {
            PhonePerceptionService active = current;
            Registration selected = active == null ? null : active.registration;
            put(out, "enabled", prefs.getBoolean("enabled", false));
            put(out, "running", active != null && active.running && selected != null && active.isCurrent(selected));
            put(out, "verified", selected != null && selected.verified);
            put(out, "state", state); put(out, "error", error == null ? JSONObject.NULL : error);
            put(out, "last_report_at", lastReportAt); put(out, "http_status", httpStatus);
            boolean confirmed = acceptedEventId != null && acceptedReportAt > 0 && acceptedReportAt == lastReportAt
                    && sameAcceptedScope(prefs.getString("server", ""), prefs.getString("session_id", ""), installation);
            put(out, "report_confirmation_schema", 1);
            put(out, "accepted_event_id", confirmed ? acceptedEventId : JSONObject.NULL);
            put(out, "accepted_report_at", confirmed ? acceptedReportAt : 0);
            put(out, "last_report_confirmed", confirmed);
            put(out, "session_id", prefs.getString("session_id", ""));
            put(out, "device_id", selected == null || selected.device == null ? JSONObject.NULL : selected.device);
            put(sections, "basic", prefs.getBoolean("basic", false)); put(sections, "app", prefs.getBoolean("app", false));
            put(sections, "music", prefs.getBoolean("music", false));
            put(out, "sections", sections); put(out, "permissions", permissions);
            put(out, "basic_interval_seconds", 60); put(out, "active_interval_seconds", 15);
        }
        return out.toString();
    }

    /** Listener access alone never starts collection; the verified user-selected music flag is also required. */
    public static boolean musicEnabled(Context context) {
        PhonePerceptionService active = current;
        Registration selected = active == null ? null : active.registration;
        return active != null && selected != null && selected.sections.music && selected.verified && active.isCurrent(selected);
    }

    public static void signalMediaChanged(Context context) {
        PhonePerceptionService active = current;
        if (active != null) active.signal();
    }

    /** Queue a fresh read through the existing debounce; never enable or restart a collector. */
    public static boolean requestReport(Context context) {
        PhonePerceptionService active = current;
        Registration selected = active == null ? null : active.registration;
        if (active == null || selected == null || !selected.verified || !active.isCurrent(selected)) return false;
        active.signal();
        return active.isCurrent(selected);
    }

    private final BroadcastReceiver screenReceiver = new BroadcastReceiver() {
        @Override public void onReceive(Context context, Intent intent) { signal(); }
    };

    @Override public void onCreate() {
        super.onCreate();
        metadata = getSharedPreferences(PREFS, MODE_PRIVATE);
        synchronized (GATE) { current = this; }
        NotificationManager notifications = getSystemService(NotificationManager.class);
        if (notifications != null) {
            NotificationChannel channel = new NotificationChannel(CHANNEL, "手机感知采集", NotificationManager.IMPORTANCE_LOW);
            channel.setDescription("仅在主动启用后上报已选择的手机状态，可随时停止。");
            notifications.createNotificationChannel(channel);
        }
        IntentFilter events = new IntentFilter();
        events.addAction(Intent.ACTION_SCREEN_ON); events.addAction(Intent.ACTION_SCREEN_OFF); events.addAction(Intent.ACTION_USER_PRESENT);
        try {
            if (Build.VERSION.SDK_INT >= 33) registerReceiver(screenReceiver, events, Context.RECEIVER_NOT_EXPORTED);
            else registerReceiver(screenReceiver, events);
            receiverRegistered = true;
        } catch (RuntimeException unavailable) { receiverRegistered = false; }
    }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && STOP.equals(intent.getAction())) { finish(null, "user_stopped"); return START_NOT_STICKY; }
        if (intent == null) {
            try { intent = restoreCommand(); }
            catch (RuntimeException unavailable) { finish(null, "restart_registration_unavailable"); return START_NOT_STICKY; }
        }
        if (intent == null || !START.equals(intent.getAction())) { finish(null, "not_enabled"); return START_NOT_STICKY; }
        try {
            long ticket = intent.getLongExtra("admission_epoch", -1);
            synchronized (GATE) { if (ticket != epoch) { if (!running) stopSelf(startId); return START_NOT_STICKY; } }
            if (Build.VERSION.SDK_INT >= 34) startForeground(NOTICE, ongoing("starting", null), ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
            else startForeground(NOTICE, ongoing("starting", null));
            if (!notificationsAllowed(this)) { finish(null, "notification_permission"); return START_NOT_STICKY; }
            String server = ApiPolicy.server(intent.getStringExtra("server"));
            String session = AttachmentPolicy.session(intent.getStringExtra("session_id"));
            String installation = installationId(this);
            Sections sections = new Sections(new JSONObject(intent.getStringExtra("sections")));
            if (!sections.any() || !installation.equals(intent.getStringExtra("installation_id"))
                    || !server.equals(new TokenVault(this).server())) { finish(null, "registration_changed"); return START_NOT_STICKY; }
            Registration selected = new Registration(server, session, installation, sections, ticket);
            synchronized (GATE) {
                if (ticket != epoch || !metadata.getBoolean("enabled", false)) return START_NOT_STICKY;
                cancelPending(); registration = selected; running = true; urgent = false;
                update(selected, "verifying", null);
                schedule(selected, 0);
            }
        } catch (Exception rejected) { finish(null, "perception_start_unavailable"); }
        return running ? START_STICKY : START_NOT_STICKY;
    }

    private Intent restoreCommand() {
        if (!metadata.getBoolean("enabled", false)) return null;
        String server = ApiPolicy.server(metadata.getString("server", ""));
        String session = AttachmentPolicy.session(metadata.getString("session_id", ""));
        JSONObject values = new JSONObject();
        put(values, "basic", metadata.getBoolean("basic", false)); put(values, "app", metadata.getBoolean("app", false));
        put(values, "music", metadata.getBoolean("music", false));
        if (!server.equals(new TokenVault(this).server())) return null;
        synchronized (GATE) {
            return new Intent(this, PhonePerceptionService.class).setAction(START)
                    .putExtra("server", server).putExtra("session_id", session).putExtra("installation_id", installationId(this))
                    .putExtra("sections", values.toString()).putExtra("admission_epoch", ++epoch);
        }
    }

    private boolean isCurrent(Registration selected) {
        if (selected == null || !running || registration != selected || current != this) return false;
        synchronized (GATE) {
            return selected.ticket == epoch && metadata != null && metadata.getBoolean("enabled", false)
                    && selected.server.equals(metadata.getString("server", ""))
                    && selected.session.equals(metadata.getString("session_id", ""))
                    && selected.sections.basic == metadata.getBoolean("basic", false)
                    && selected.sections.app == metadata.getBoolean("app", false)
                    && selected.sections.music == metadata.getBoolean("music", false);
        }
    }

    private void signal() {
        synchronized (GATE) {
            Registration selected = registration;
            if (!isCurrent(selected)) return;
            urgent = true;
            if (!inFlight) schedule(selected, Math.max(0, FAST_MS - (SystemClock.elapsedRealtime() - selected.lastStarted)));
        }
    }

    private void schedule(Registration selected, long delay) {
        synchronized (GATE) {
            if (!isCurrent(selected) || executor.isShutdown()) return;
            if (pending != null) pending.cancel(false);
            pending = executor.schedule(() -> cycle(selected), Math.max(0, delay), TimeUnit.MILLISECONDS);
        }
    }

    private void cycle(Registration selected) {
        boolean forced;
        synchronized (GATE) {
            if (!isCurrent(selected) || inFlight) return;
            long remaining = FAST_MS - (SystemClock.elapsedRealtime() - selected.lastStarted);
            if (remaining > 0) { schedule(selected, remaining); return; }
            inFlight = true; forced = urgent; urgent = false; selected.lastStarted = SystemClock.elapsedRealtime();
        }
        long interval = selected.sections.app || selected.sections.music ? FAST_MS : BASIC_MS;
        boolean reportStarted = false;
        try {
            if (!notificationsAllowed(this)) throw new Rejected("notification_permission");
            String bearer = credentials(selected);
            update(selected, "verifying", null);
            String query = "?session_id=" + URLEncoder.encode(selected.session, "UTF-8")
                    + "&installation_id=" + URLEncoder.encode(selected.installation, "UTF-8");
            JSONObject config = request(selected, bearer, "/chat/perception/config" + query, null);
            verifyConfig(selected, config);
            if (!isCurrent(selected)) return;
            selected.verified = true;
            boolean basic = selected.sections.basic && (forced || SystemClock.elapsedRealtime() - selected.lastBasic >= BASIC_MS);
            if (selected.sections.music) PerceptionMediaListener.refresh(this);
            else PerceptionMediaListener.clear();
            JSONObject frame = PhonePerceptionCollector.build(this, basic, selected.sections.app, selected.sections.music);
            if (!isCurrent(selected)) return;
            // Permission revocation after a section was read removes it before any POST.
            if (!PhonePerceptionCollector.usagePermissionGranted(this)) frame.remove("app");
            if (!selected.sections.music || !PerceptionMediaListener.permissionGranted(this)) { frame.remove("music"); PerceptionMediaListener.clear(); }
            if (frame.length() <= 1) { update(selected, "waiting_for_permission", "no_available_sections"); return; }
            String eventId = UUID.randomUUID().toString();
            JSONObject body = new JSONObject().put("session_id", selected.session).put("installation_id", selected.installation)
                    .put("event_id", eventId).put("frame", frame);
            if (body.toString().getBytes(StandardCharsets.UTF_8).length > 32768) throw new Rejected("report_too_large");
            bearer = credentials(selected);
            update(selected, "syncing", null);
            reportStarted = true;
            JSONObject response = request(selected, bearer, "/chat/perception/report", body);
            verifyEcho(selected, response);
            if (!isCurrent(selected)) return;
            if (!acceptedReport(response, eventId)) {
                boolean rejected = "rejected".equals(response.opt("state"));
                update(selected, rejected ? "waiting_for_bridge" : "report_unknown",
                        rejected ? "report_rejected" : "report_outcome_unknown");
                interval = Math.max(interval, BASIC_MS);
                return;
            }
            if (basic) selected.lastBasic = SystemClock.elapsedRealtime();
            synchronized (GATE) {
                if (isCurrent(selected)) {
                    acceptedEventId = eventId;
                    acceptedServer = selected.server; acceptedSession = selected.session; acceptedInstallation = selected.installation;
                    acceptedReportAt = System.currentTimeMillis() / 1000.0;
                    lastReportAt = acceptedReportAt;
                }
            }
            update(selected, "running", null);
        } catch (Rejected rejected) { finish(selected, rejected.reason); }
        catch (Exception unavailable) {
            update(selected, reportStarted ? "report_unknown" : "waiting_for_network",
                    reportStarted ? "report_outcome_unknown" : "configuration_unavailable");
            interval = Math.max(interval, BASIC_MS);
        } finally {
            synchronized (GATE) {
                inFlight = false;
                if (isCurrent(selected)) {
                    long next = urgent ? FAST_MS : interval;
                    schedule(selected, Math.max(0, next - (SystemClock.elapsedRealtime() - selected.lastStarted)));
                }
            }
        }
    }

    private String credentials(Registration selected) throws Rejected {
        if (!isCurrent(selected)) throw new Rejected("registration_changed");
        TokenVault vault = new TokenVault(this);
        if (!selected.server.equals(vault.server())) throw new Rejected("server_changed");
        String bearer = vault.load(selected.server);
        if (!ApiPolicy.jwt(bearer)) throw new Rejected("login_required");
        try {
            String fingerprint = hex(MessageDigest.getInstance("SHA-256").digest(bearer.getBytes(StandardCharsets.UTF_8)));
            if (selected.authentication == null) selected.authentication = fingerprint;
            else if (!selected.authentication.equals(fingerprint)) throw new Rejected("authentication_changed");
        } catch (Rejected rejected) { throw rejected; }
        catch (Exception unavailable) { throw new Rejected("authentication_unavailable"); }
        return bearer;
    }

    private JSONObject request(Registration selected, String bearer, String path, JSONObject body) throws Exception {
        if (!isCurrent(selected)) throw new Rejected("registration_changed");
        HttpsURLConnection request = null;
        try {
            String fixed = ApiPolicy.requestPath(path);
            request = (HttpsURLConnection) new URL(selected.server + fixed).openConnection();
            synchronized (GATE) { if (!isCurrent(selected)) throw new Rejected("registration_changed"); connection = request; }
            PinnedTls.configure(request, selected.server);
            request.setInstanceFollowRedirects(false);
            request.setConnectTimeout(10000); request.setReadTimeout(15000);
            request.setRequestMethod(body == null ? "GET" : "POST");
            request.setRequestProperty("Accept", "application/json");
            request.setRequestProperty("User-Agent", "AsteriaChat/" + BuildConfig.VERSION_NAME + " PhonePerception");
            request.setRequestProperty("Authorization", "Bearer " + bearer);
            if (!isCurrent(selected)) throw new Rejected("registration_changed");
            if (body != null) {
                byte[] bytes = body.toString().getBytes(StandardCharsets.UTF_8);
                request.setDoOutput(true); request.setRequestProperty("Content-Type", "application/json; charset=utf-8");
                request.setFixedLengthStreamingMode(bytes.length);
                try (OutputStream stream = request.getOutputStream()) { stream.write(bytes); }
            }
            int code = request.getResponseCode();
            synchronized (GATE) { if (isCurrent(selected)) httpStatus = code; }
            if (!isCurrent(selected)) throw new Rejected("registration_changed");
            if (code == 401) throw new Rejected("login_expired");
            if (code == 403) throw new Rejected("perception_permission_revoked");
            if (code == 404) throw new Rejected("perception_api_unavailable");
            if (code == 400 || code == 409) throw new Rejected("perception_registration_rejected");
            if (code < 200 || code >= 300) throw new java.io.IOException("perception_request_unavailable");
            JSONObject envelope = new JSONObject(read(request.getInputStream()));
            if (envelope.has("status") && !"ok".equals(envelope.optString("status")))
                throw new java.io.IOException("perception_request_not_confirmed");
            if (envelope.has("ok") && !envelope.optBoolean("ok", false)) throw new java.io.IOException("perception_request_not_confirmed");
            JSONObject result = envelope.optJSONObject("data");
            if (result == null) {
                if (body != null) throw new java.io.IOException("report_response_data_missing");
                result = envelope;
            }
            verifyEcho(selected, result);
            return result;
        } finally {
            if (request != null) request.disconnect();
            synchronized (GATE) { if (connection == request) connection = null; }
        }
    }

    private void verifyConfig(Registration selected, JSONObject config) throws Rejected {
        if (!(config.opt("enabled") instanceof Boolean) || !config.optBoolean("enabled", false)) throw new Rejected("server_enrollment_disabled");
        if (!selected.installation.equals(config.optString("installation_id", ""))) throw new Rejected("installation_mismatch");
        Sections granted;
        try { granted = new Sections(config.optJSONObject("sections")); }
        catch (RuntimeException invalid) { throw new Rejected("server_sections_invalid"); }
        if (!selected.sections.same(granted)) throw new Rejected("server_sections_changed");
        String device = config.optString("device_id", "");
        if (!device.matches("[A-Za-z0-9_.-]{1,64}")) throw new Rejected("device_binding_required");
        if (selected.device != null && !selected.device.equals(device)) throw new Rejected("device_binding_changed");
        selected.device = device;
        verifyEcho(selected, config);
    }

    static boolean acceptedReport(JSONObject response, String eventId) {
        return response != null && eventId != null && "accepted".equals(response.opt("state"))
                && eventId.equals(response.opt("report_id"));
    }

    static boolean sameAcceptedScope(String server, String session, String installation) {
        return server != null && server.equals(acceptedServer) && session != null && session.equals(acceptedSession)
                && installation != null && installation.equals(acceptedInstallation);
    }

    private static void invalidateAcceptedIdentity(String reason) {
        if ("logged_out".equals(reason) || "server_changed".equals(reason) || "authentication_changed".equals(reason)
                || "login_expired".equals(reason) || "login_required".equals(reason)
                || "installation_mismatch".equals(reason) || "session_mismatch".equals(reason)) {
            // Keep the old timestamp as unverified history; it is no proof for a new identity.
            acceptedEventId = null; acceptedReportAt = 0;
            acceptedServer = null; acceptedSession = null; acceptedInstallation = null;
        }
    }

    private static void verifyEcho(Registration selected, JSONObject value) throws Rejected {
        if (value.has("session_id") && !selected.session.equals(value.optString("session_id", ""))) throw new Rejected("session_mismatch");
        if (value.has("installation_id") && !selected.installation.equals(value.optString("installation_id", ""))) throw new Rejected("installation_mismatch");
    }

    private void update(Registration selected, String nextState, String reason) {
        synchronized (GATE) {
            if (!isCurrent(selected)) return;
            boolean changed = !nextState.equals(state) || (reason == null ? error != null : !reason.equals(error));
            state = nextState; error = reason;
            if (!changed) return;
        }
        main.post(() -> {
            synchronized (GATE) {
                // A superseded update must never replace a newer state or revive a stopped notice.
                if (!isCurrent(selected) || !nextState.equals(state)
                        || (reason == null ? error != null : !reason.equals(error))) return;
                NotificationManager manager = getSystemService(NotificationManager.class);
                if (manager != null) {
                    try { manager.notify(NOTICE, ongoing(nextState, reason)); }
                    catch (RuntimeException unavailable) { /* The next tick still rechecks notification permission. */ }
                }
            }
        });
    }

    private void finish(Registration selected, String reason) {
        final long ticket;
        synchronized (GATE) {
            if (current != this || selected != null && registration != selected) return;
            ticket = ++epoch;
            running = false; registration = null; state = "stopped"; error = reasonCode(reason);
            invalidateAcceptedIdentity(reason);
            if (metadata != null) metadata.edit().putBoolean("enabled", false).commit();
            cancelPending();
        }
        PerceptionMediaListener.clear();
        main.post(() -> {
            synchronized (GATE) {
                if (current == this && ticket == epoch) { stopForeground(STOP_FOREGROUND_REMOVE); stopSelf(); }
            }
        });
    }

    private void cancelPending() {
        if (pending != null) pending.cancel(false);
        HttpsURLConnection active = connection;
        if (active != null) active.disconnect();
    }

    static String notificationText(String value, String reason) {
        if ("starting".equals(value)) return "正在启动手机感知，尚未核验设备与采集范围";
        if ("verifying".equals(value)) return "正在核验设备与采集范围，本轮尚未上报";
        if ("waiting_for_permission".equals(value)) return "等待已选项目的权限或可用状态，当前未上报";
        if ("syncing".equals(value)) return "正在同步已选手机状态，结果待确认";
        if ("report_unknown".equals(value)) return "本轮同步结果未知，未记为成功；等待下次检查";
        if ("waiting_for_bridge".equals(value)) return "感知桥未接受本轮上报，等待下次检查";
        if ("waiting_for_network".equals(value)) {
            if ("report_outcome_unknown".equals(reason)) return "本轮同步结果未知，等待下次检查；可随时停止";
            if ("configuration_unavailable".equals(reason)) return "暂时无法核验服务器配置，等待网络恢复";
            return "暂时无法确认手机状态同步，等待下次检查";
        }
        if ("running".equals(value)) return "按已选项目定时同步手机状态，可随时停止";
        if ("stopped".equals(value)) return "手机感知已停止";
        return "手机感知状态待确认，请打开应用查看";
    }

    private Notification ongoing(String value, String reason) {
        PendingIntent stop = PendingIntent.getService(this, NOTICE,
                new Intent(this, PhonePerceptionService.class).setAction(STOP), PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        PendingIntent open = PendingIntent.getActivity(this, NOTICE, new Intent(this, MainActivity.class)
                .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP | Intent.FLAG_ACTIVITY_CLEAR_TOP), PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        return new Notification.Builder(this, CHANNEL).setSmallIcon(R.drawable.ic_notification)
                .setContentTitle(BuildConfig.APP_NAME + " 手机感知").setContentText(notificationText(value, reason))
                .setOnlyAlertOnce(true).setOngoing(true).setCategory(Notification.CATEGORY_SERVICE).setContentIntent(open)
                .addAction(new Notification.Action.Builder(android.R.drawable.ic_media_pause, "停止采集", stop).build()).build();
    }

    private static boolean notificationsAllowed(Context context) {
        try {
            if (Build.VERSION.SDK_INT >= 33 && context.checkSelfPermission("android.permission.POST_NOTIFICATIONS") != PackageManager.PERMISSION_GRANTED) return false;
            NotificationManager manager = context.getSystemService(NotificationManager.class);
            if (manager == null || !manager.areNotificationsEnabled()) return false;
            NotificationChannel channel = manager.getNotificationChannel(CHANNEL);
            return channel == null || channel.getImportance() != NotificationManager.IMPORTANCE_NONE;
        } catch (RuntimeException unavailable) { return false; }
    }

    private static String read(InputStream source) throws Exception {
        try (InputStream input = source; ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[4096]; int length;
            while ((length = input.read(buffer)) != -1) {
                if (out.size() + length > 65536) throw new java.io.IOException("perception_response_too_large");
                out.write(buffer, 0, length);
            }
            return new String(out.toByteArray(), StandardCharsets.UTF_8);
        }
    }

    private static String hex(byte[] value) {
        StringBuilder out = new StringBuilder(value.length * 2);
        for (byte part : value) out.append(String.format(java.util.Locale.ROOT, "%02x", part & 255));
        return out.toString();
    }

    private static String reasonCode(String value) {
        return value != null && value.matches("[a-z][a-z0-9_]{0,79}") ? value : "user_stopped";
    }

    private static void put(JSONObject target, String key, Object value) {
        try { target.put(key, value); } catch (Exception unavailable) { }
    }

    @Override public void onTimeout(int startId, int fgsType) { finish(null, "system_time_limit"); }
    @Override public IBinder onBind(Intent intent) { return null; }
    @Override public void onDestroy() {
        boolean owned;
        synchronized (GATE) {
            owned = current == this;
            running = false; registration = null; cancelPending(); executor.shutdownNow();
            if (owned) { current = null; state = "stopped"; if (metadata.getBoolean("enabled", false)) error = "service_interrupted"; }
        }
        if (owned) PerceptionMediaListener.clear();
        if (receiverRegistered) { try { unregisterReceiver(screenReceiver); } catch (RuntimeException unavailable) { } }
        super.onDestroy();
    }
}
