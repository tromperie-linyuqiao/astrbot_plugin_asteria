package com.asteria.chat;

import android.app.Activity;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.Intent;
import android.content.ClipData;
import android.database.Cursor;
import android.graphics.Color;
import android.net.Uri;
import android.net.http.SslError;
import android.os.Build;
import android.os.Bundle;
import android.provider.OpenableColumns;
import android.provider.Settings;
import android.util.Base64;
import android.webkit.JavascriptInterface;
import android.webkit.SslErrorHandler;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.Toast;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import javax.net.ssl.HttpsURLConnection;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

public final class MainActivity extends Activity {
    private static final String HOME = "file:///android_asset/index.html";
    private static final int MAX_REQUEST = 1024 * 1024;
    private static final int MAX_RESPONSE = 8 * 1024 * 1024;
    private static final int ATTACHMENT_PICKER = 6401;
    private static final int SPEECH_RECOGNIZER = 6403;
    private static final String CHANNEL_ID = "texas-chat-replies";
    private static final int NOTIFICATION_PERMISSION = 6402;
    private static final AttachmentCacheRecovery ATTACHMENT_RECOVERY = new AttachmentCacheRecovery();
    private final AtomicBoolean localPage = new AtomicBoolean(false);
    private final AtomicBoolean destroyed = new AtomicBoolean(false);
    private final AtomicBoolean foreground = new AtomicBoolean(false);
    private WebView web;
    private ChatViewportController viewport;
    private NativeBridge bridge;
    private TexasVoice voice;
    private ReplyWatchService.Observer replyWatchObserver;
    private Intent pendingReplyIntent;
    private boolean replyAccountSwitching;
    private JSONObject attachmentRecovery = json("status", "not_attempted");

    private static final class AuthState {
        final String server, token;
        final long epoch;
        AuthState(String server, String token, long epoch) { this.server = server; this.token = token; this.epoch = epoch; }
    }

    private static final class PickerRequest {
        final String requestId, sessionId, kind;
        final AuthState auth;
        final ConversationExport.Document document;
        PickerRequest(String requestId, String sessionId, AuthState auth) {
            this(requestId, sessionId, auth, "attachment");
        }
        PickerRequest(String requestId, String sessionId, AuthState auth, String kind) {
            this.requestId = requestId; this.sessionId = sessionId; this.auth = auth; this.kind = kind;
            this.document = null;
        }
        PickerRequest(String requestId, AuthState auth, ConversationExport.Document document) {
            this.requestId = requestId; this.sessionId = null; this.auth = auth; this.kind = "export";
            this.document = document;
        }
    }

    private static final class AppearanceBytes extends ByteArrayOutputStream {
        AppearanceBytes() { super(64 * 1024); }
        byte[] contents() { return buf; }
    }

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        captureReplyIntent(getIntent());
        try {
            AttachmentCacheRecovery.Result recovered = ATTACHMENT_RECOVERY.recoverBeforeWriters(
                    AttachmentFileProvider.directory(this));
            attachmentRecovery = json("status", recovered.status, "removed", recovered.removed, "failed", recovered.failed);
        } catch (Exception unavailable) { attachmentRecovery = json("status", "unavailable"); }
        getWindow().setStatusBarColor(Color.rgb(22, 26, 24));
        getWindow().setNavigationBarColor(Color.rgb(22, 26, 24));
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationManager channels = getSystemService(NotificationManager.class);
            NotificationChannels.ensure(channels);
        }
        web = new WebView(this);
        web.setBackgroundColor(Color.rgb(22, 26, 24));
        WebView.setWebContentsDebuggingEnabled(false);
        WebSettings settings = web.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setAllowFileAccessFromFileURLs(false);
        settings.setAllowUniversalAccessFromFileURLs(false);
        settings.setJavaScriptCanOpenWindowsAutomatically(false);
        settings.setSupportMultipleWindows(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setSafeBrowsingEnabled(true);
        settings.setMediaPlaybackRequiresUserGesture(true);
        bridge = new NativeBridge();
        voice = new TexasVoice(this, value -> {if(trusted() && web!=null) web.evaluateJavascript("window.ChatVoice&&window.ChatVoice.receive("+value.toString()+")",null);});
        if (bridge.token == null) {
            PhonePerceptionService.stop(this, "login_required");
            // Explicit saved background accounts remain independent of the visible login.
        }
        web.addJavascriptInterface(bridge, "AsteriaChat");
        web.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                String url = request.getUrl().toString();
                if (isHome(url)) return false;
                if (request.isForMainFrame() && request.hasGesture()) openExternal(request.getUrl());
                return true;
            }

            @Override public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                String url = request.getUrl().toString();
                if (isAsset(url)) return null;
                // Every network operation belongs to NativeBridge; remote frames/scripts/images get no bridge.
                return new WebResourceResponse("text/plain", "UTF-8", 403, "Blocked", null,
                        new ByteArrayInputStream(new byte[0]));
            }

            @Override public void onPageStarted(WebView view, String url, android.graphics.Bitmap icon) {
                localPage.set(isHome(url));
                if (!isHome(url)) {
                    view.removeJavascriptInterface("AsteriaChat");
                    view.stopLoading();
                }
            }

            @Override public void onReceivedSslError(WebView view, SslErrorHandler handler, SslError error) {
                handler.cancel();
            }

            @Override public void onPageFinished(WebView view, String url) {
                if (isHome(url)) {
                    if (viewport != null) viewport.refresh();
                    dispatchPendingReply();
                }
            }
        });
        FrameLayout content = new FrameLayout(this);
        content.setBackgroundColor(Color.rgb(22, 26, 24));
        content.addView(web, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT));
        setContentView(content);
        viewport = new ChatViewportController(getWindow(), content, web, this::notifyViewportChanged);
        viewport.attach();
        replyWatchObserver = value -> runOnUiThread(() -> {
            if (trusted() && web != null) web.evaluateJavascript(
                "if(window.AsteriaChatUI&&typeof window.AsteriaChatUI.replyWatchChanged==='function'){window.AsteriaChatUI.replyWatchChanged("
                        + value + ");}", null);
        });
        ReplyWatchService.setObserver(replyWatchObserver);
        localPage.set(true);
        web.loadUrl(HOME);
    }

    private boolean trusted() { return localPage.get() && !destroyed.get(); }

    private static boolean isHome(String url) { return HOME.equals(url) || (url != null && url.startsWith(HOME + "#")); }

    private static boolean isAsset(String url) {
        if (url == null || !url.startsWith("file:///android_asset/") || url.contains("..") || url.contains("%"))
            return false;
        return url.indexOf('?') < 0 && url.indexOf('#') < 0;
    }

    private void openExternal(Uri uri) {
        if (!("https".equalsIgnoreCase(uri.getScheme()) || "http".equalsIgnoreCase(uri.getScheme()))) return;
        try { startActivity(new Intent(Intent.ACTION_VIEW, uri).addCategory(Intent.CATEGORY_BROWSABLE)); }
        catch (RuntimeException noBrowser) { Toast.makeText(this, "没有可用的浏览器", Toast.LENGTH_SHORT).show(); }
    }

    @Override public void onBackPressed() {
        if (web != null && trusted()) web.evaluateJavascript(
                "Boolean(window.AsteriaChatUI&&window.AsteriaChatUI.back&&window.AsteriaChatUI.back())",
                result -> { if (!"true".equals(result)) MainActivity.super.onBackPressed(); });
        else super.onBackPressed();
    }

    @Override protected void onResume() {
        super.onResume();
        if (destroyed.get()) return;
        foreground.set(true);
        if (bridge != null) synchronized (bridge.lock) {
            ReplyWatchService.setVisibleAccount(bridge.server, bridge.token, bridge.visibleSession);
        }
        ReplyWatchService.setAppForeground(true);
        ReplyWatchService.resumeEnabled(this);
        if (web != null && !destroyed.get()) web.onResume();
        if (viewport != null) viewport.refresh();
        notifyForegroundChanged();
        dispatchPendingReply();
    }

    @Override protected void onPause() {
        if(voice!=null)voice.background();
        foreground.set(false);
        ReplyWatchService.setAppForeground(false);
        notifyForegroundChanged();
        if (web != null && !destroyed.get()) web.onPause();
        super.onPause();
    }

    private void notifyForegroundChanged() {
        if (!trusted() || web == null) return;
        web.evaluateJavascript("if(window.AsteriaChatUI&&typeof window.AsteriaChatUI.foregroundChanged==='function'){window.AsteriaChatUI.foregroundChanged();}", null);
    }

    private void notifyViewportChanged(String metrics) {
        if (!trusted() || web == null || !foreground.get()) return;
        web.evaluateJavascript("if(window.AsteriaChatUI&&typeof window.AsteriaChatUI.viewportChanged==='function'){window.AsteriaChatUI.viewportChanged("
                + metrics + ");}", null);
    }

    @Override protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        captureReplyIntent(intent);
        dispatchPendingReply();
    }

    private void captureReplyIntent(Intent intent) {
        if (intent != null && intent.hasExtra("reply_watch_scope")) pendingReplyIntent = new Intent(intent);
    }

    private void dispatchPendingReply() {
        if (!trusted() || web == null || bridge == null || pendingReplyIntent == null || replyAccountSwitching) return;
        final Intent selected = pendingReplyIntent;
        final String session;
        final String sourceServer, sourceUser;
        final long sourceEpoch;
        synchronized (bridge.lock) {
            session = ReplyWatchService.notificationSession(selected, bridge.server, bridge.token);
            sourceServer = bridge.server;
            sourceUser = AttachmentCache.username(bridge.token);
            sourceEpoch = bridge.epoch;
        }
        if (session == null) {
            final String accountId = selected.getStringExtra("reply_watch_scope");
            final ReplyWatchAccounts.Record account = ReplyWatchAccounts.find(this, accountId);
            if (account == null || !account.server.equals(selected.getStringExtra("reply_watch_server"))
                    || !account.session.equals(selected.getStringExtra("session_id"))
                    || !ReplyWatchAccounts.matches(this, account)) { pendingReplyIntent = null; return; }
            replyAccountSwitching = true;
            web.evaluateJavascript("Boolean(window.AsteriaChatUI&&window.AsteriaChatUI.prepareAccountSwitch&&window.AsteriaChatUI.prepareAccountSwitch())", ready -> {
                replyAccountSwitching = false;
                if (!"true".equals(ready) || pendingReplyIntent != selected || destroyed.get()) return;
                try { bridge.activateSavedReplyAccount(accountId); web.reload(); }
                catch (Exception unavailable) { pendingReplyIntent = null; }
            });
            return;
        }
        String notifiedMessage = selected.getStringExtra("reply_message_id");
        if (notifiedMessage == null || notifiedMessage.length() > 160) notifiedMessage = "";
        String clickTarget = "conversation".equals(selected.getStringExtra("reply_click_target")) ? "conversation" : "message";
        web.evaluateJavascript("Boolean(window.AsteriaChatUI&&typeof window.AsteriaChatUI.openConversation==='function'"
                + "&&window.AsteriaChatUI.openConversation(" + JSONObject.quote(session) + "," + JSONObject.quote(notifiedMessage) + "," + JSONObject.quote(clickTarget)
                + "," + json("server", sourceServer, "username", sourceUser) + "))", result -> {
            synchronized (bridge.lock) {
                // A queued UI call must not later switch back after the user chose another account.
                if (pendingReplyIntent == selected && ("true".equals(result) || bridge.epoch != sourceEpoch)) pendingReplyIntent = null;
            }
        });
    }

    @Override protected void onDestroy() {
        foreground.set(false);
        ReplyWatchService.setAppForeground(false);
        destroyed.set(true);
        localPage.set(false);
        if (replyWatchObserver != null) {
            ReplyWatchService.clearObserver(replyWatchObserver);
            replyWatchObserver = null;
        }
        if (viewport != null) { viewport.close(); viewport = null; }
        if (voice != null) {voice.close();voice=null;}
        if (bridge != null) bridge.close();
        if (web != null) {
            web.removeJavascriptInterface("AsteriaChat");
            web.stopLoading();
            web.destroy();
            web = null;
        }
        super.onDestroy();
    }

    @Override protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == SPEECH_RECOGNIZER && bridge != null) bridge.recognitionResult(resultCode,data);
        if (requestCode == ATTACHMENT_PICKER && bridge != null) bridge.selectionResult(resultCode, data);
    }

    @Override public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode != NOTIFICATION_PERMISSION || !trusted() || web == null) return;
        boolean granted = grantResults.length > 0 && grantResults[0] == android.content.pm.PackageManager.PERMISSION_GRANTED;
        web.evaluateJavascript("if(window.AsteriaChatUI&&typeof window.AsteriaChatUI.notificationPermissionChanged==='function'){window.AsteriaChatUI.notificationPermissionChanged("
                + granted + ");}", null);
    }

    private final class NativeBridge {
        private final Object lock = new Object();
        private final TokenVault vault = new TokenVault(MainActivity.this);
        private final ThreadPoolExecutor executor = new ThreadPoolExecutor(2, 2, 0L, TimeUnit.MILLISECONDS,
                new ArrayBlockingQueue<Runnable>(32), runnable -> {
                    Thread thread = new Thread(runnable, "texas-chat-http");
                    thread.setDaemon(true);
                    return thread;
                }, new ThreadPoolExecutor.AbortPolicy());
        private String server = vault.server();
        private String token = vault.load(server);
        private long epoch = 0;
        // Every access is serialized by lock, including admission on the UI thread.
        private long perceptionEpoch = 0;
        private final java.util.Set<HttpURLConnection> active = new java.util.HashSet<>();
        private final java.util.Set<java.io.Closeable> activeSources = new java.util.HashSet<>();
        private PickerRequest picker;
        private String visibleSession = "";

        @JavascriptInterface public String getViewportMetrics() {
            ChatViewportController value = viewport;
            return trusted() && value != null ? value.snapshot() : "{}";
        }

        @JavascriptInterface public String getConfig() {
            if (!trusted()) return json("error", "local_page_required").toString();
            synchronized (lock) {
                return json("server", server, "authenticated", token != null, "username", AttachmentCache.username(token), "version", BuildConfig.VERSION_NAME,
                        "foreground", foreground.get(),
                        "replyWatch", decode(ReplyWatchService.snapshot(MainActivity.this), "application/json"),
                        "localOnly", true, "tlsCertificatePin", !BuildConfig.DEFAULT_CERT_SHA256.isEmpty(),
                        "attachmentCacheRecovery", attachmentRecovery).toString();
            }
        }

        @JavascriptInterface public String getReplyWatchStatus() {
            return trusted() ? ReplyWatchService.snapshot(MainActivity.this) : json("ok", false, "error", "local_page_required").toString();
        }

        private JSONObject activateSavedReplyAccount(String accountId) throws Exception {
            ReplyWatchAccounts.Record selected = ReplyWatchAccounts.find(MainActivity.this, accountId);
            if (selected == null || !ReplyWatchAccounts.matches(MainActivity.this, selected))
                throw new IllegalStateException("saved_account_unavailable");
            synchronized (lock) {
                if (picker != null) throw new IllegalStateException("picker_in_progress");
                vault.save(selected.server, selected.token);
                PhonePerceptionService.stop(MainActivity.this, "server_changed");
                epoch++;
                runOnUiThread(() -> {if(voice!=null)voice.stop();}); server = selected.server; token = selected.token; visibleSession = selected.session;
            }
            ReplyWatchService.setVisibleAccount(selected.server, selected.token, selected.session);
            return json("ok", true, "config", decode(getConfig(), "application/json"));
        }

        @JavascriptInterface public String activateReplyAccount(String accountId) {
            if (!trusted() || !foreground.get()) return json("ok", false, "error", "foreground_required").toString();
            try { return activateSavedReplyAccount(accountId).toString(); }
            catch (Exception unavailable) { return json("ok", false, "error", "saved_account_unavailable").toString(); }
        }

        @JavascriptInterface public String rememberReplyAccount(String sessionId, String title, String lastId, String excerpt) {
            if (!trusted() || !foreground.get()) return json("ok", false, "error", "foreground_required").toString();
            try {
                AttachmentPolicy.session(sessionId);
                AuthState auth = attachmentAuth();
                synchronized (lock) {
                    requireCurrent(auth);
                    if (!sessionId.equals(visibleSession) || !auth.token.equals(vault.load(auth.server)))
                        throw new IllegalStateException("saved_login_required");
                    ReplyWatchService.rememberAccount(MainActivity.this, auth.server, auth.token, sessionId, title, lastId, excerpt);
                }
                return json("ok", true, "service_started", false).toString();
            } catch (RuntimeException unavailable) { return json("ok", false, "error", "saved_account_unavailable").toString(); }
        }

        @JavascriptInterface public String startReplyWatchAccount(String accountId) {
            if (!trusted() || !foreground.get()) return json("ok", false, "error", "foreground_required").toString();
            try {
                ReplyWatchAccounts.Record record = ReplyWatchAccounts.find(MainActivity.this, accountId);
                if (record == null) throw new IllegalStateException("saved_account_unavailable");
                if (!NotificationPreferences.load(MainActivity.this).enabled)
                    throw new IllegalStateException("notifications_disabled");
                if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission("android.permission.POST_NOTIFICATIONS")
                        != android.content.pm.PackageManager.PERMISSION_GRANTED) throw new IllegalStateException("notification_permission");
                runOnUiThread(() -> {
                    if (foreground.get() && ReplyWatchAccounts.matches(MainActivity.this, record)) {
                        try { ReplyWatchService.start(MainActivity.this, record.server, record.token, record.session, record.title, record.baseline); }
                        catch (RuntimeException unavailable) { /* Read actual target status; never report started here. */ }
                    }
                });
                return json("ok", true, "account_id", accountId, "state", "starting").toString();
            } catch (RuntimeException unavailable) { return json("ok", false, "error", unavailable.getMessage()).toString(); }
        }

        @JavascriptInterface public String stopReplyWatchAccount(String accountId) {
            if (!trusted() || !foreground.get()) return json("ok", false, "error", "foreground_required").toString();
            if (accountId == null || !accountId.matches("[0-9a-f]{64}")) return json("ok", false, "error", "invalid_account").toString();
            ReplyWatchService.stopTarget(MainActivity.this, accountId, "user_stopped");
            return json("ok", true, "account_id", accountId, "stopped", true).toString();
        }

        @JavascriptInterface public String getNotificationPreferences() {
            return trusted() ? NotificationPreferences.load(MainActivity.this).json().toString()
                    : json("ok", false, "error", "local_page_required").toString();
        }

        @JavascriptInterface public String setNotificationPreferences(String value) {
            if (!trusted() || !foreground.get()) return json("ok", false, "error", "foreground_required").toString();
            try {
                NotificationPreferences saved = NotificationPreferences.save(MainActivity.this, value);
                ReplyWatchService.preferencesChanged(MainActivity.this, saved);
                return saved.json().toString();
            } catch (Exception invalid) { return json("ok", false, "error", "notification_preferences_not_saved").toString(); }
        }

        @JavascriptInterface public String setNotificationIdentity(String sessionId, String name, String avatarDataUrl) {
            try {
                AttachmentPolicy.session(sessionId); AuthState auth = attachmentAuth();
                synchronized (lock) {
                    requireCurrent(auth);
                    NotificationIdentity.save(MainActivity.this, ReplyWatchService.scope(auth.server, auth.token, sessionId), name, avatarDataUrl);
                    synchronized (lock) { visibleSession = sessionId; }
                    ReplyWatchService.setVisibleAccount(auth.server, auth.token, sessionId);
                }
                return json("ok", true).toString();
            } catch (Exception invalid) { return json("ok", false, "error", "notification_identity_unavailable").toString(); }
        }

        @JavascriptInterface public String getAttachmentCacheStatus() {
            if (!trusted()) return json("ok", false, "error", "local_page_required").toString();
            try { return AttachmentCache.status(MainActivity.this).toString(); }
            catch (Exception unavailable) { return json("ok", false, "error", "cache_unavailable").toString(); }
        }

        @JavascriptInterface public String clearRecoverableAttachmentCache() {
            if (!trusted() || !foreground.get()) return json("ok", false, "error", "foreground_required").toString();
            try { return AttachmentCache.clear(MainActivity.this).toString(); }
            catch (Exception unavailable) { return json("ok", false, "error", "cache_clear_failed").toString(); }
        }

        @JavascriptInterface public String getNotificationStatus() {
            return trusted() ? ReplyWatchService.notificationStatus(MainActivity.this)
                    : json("ok", false, "error", "local_page_required", "heads_up_guaranteed", false).toString();
        }

        @JavascriptInterface public String openNotificationCategorySettings(String kind) {
            if (!trusted() || !foreground.get()) return json("ok", false, "error", "foreground_required").toString();
            boolean watch = "watch".equals(kind);
            if (!watch && !NotificationChannels.validKind(kind)) return json("ok", false, "error", "invalid_category").toString();
            String channelId = watch ? ReplyWatchService.WATCH_CHANNEL : NotificationChannels.id(kind);
            if (watch) {
                NotificationManager manager = getSystemService(NotificationManager.class);
                if (manager == null || manager.getNotificationChannel(channelId) == null)
                    return json("ok", false, "error", "watch_channel_not_created").toString();
            }
            Intent settings = new Intent(android.provider.Settings.ACTION_CHANNEL_NOTIFICATION_SETTINGS)
                    .putExtra(android.provider.Settings.EXTRA_APP_PACKAGE, getPackageName())
                    .putExtra(android.provider.Settings.EXTRA_CHANNEL_ID, channelId);
            if (!watch && settings.resolveActivity(getPackageManager()) == null) settings = new Intent(android.provider.Settings.ACTION_APP_NOTIFICATION_SETTINGS)
                    .putExtra(android.provider.Settings.EXTRA_APP_PACKAGE, getPackageName());
            if (settings.resolveActivity(getPackageManager()) == null) return json("ok", false, "error", "notification_settings_unavailable").toString();
            final Intent destination = settings;
            runOnUiThread(() -> {
                if (!trusted() || !foreground.get()) return;
                try { startActivity(destination); }
                catch (RuntimeException unavailable) { Toast.makeText(MainActivity.this, "请从手机设置查看 Asteria Chat 的通知类别。", Toast.LENGTH_LONG).show(); }
            });
            return json("ok", true, "settings_opening", true, "category", kind).toString();
        }

        @JavascriptInterface public String testLocalNotification(String kind) {
            if (!trusted() || !foreground.get()) return json("ok", false, "error", "foreground_required").toString();
            if (!NotificationChannels.validKind(kind)) return json("ok", false, "error", "invalid_category").toString();
            try {
                NotificationManager manager = getSystemService(NotificationManager.class);
                if (manager == null || !manager.areNotificationsEnabled() || (Build.VERSION.SDK_INT >= 33
                        && checkSelfPermission("android.permission.POST_NOTIFICATIONS") != android.content.pm.PackageManager.PERMISSION_GRANTED))
                    return json("ok", false, "error", "notification_permission").toString();
                if (!NotificationChannels.allowed(manager, kind)) return json("ok", false, "error", "notification_channel_blocked").toString();
                if (!NotificationPreferences.load(MainActivity.this).allows(kind, java.util.Calendar.getInstance()))
                    return json("ok", false, "error", "notification_preference_or_quiet").toString();
                android.app.PendingIntent open = android.app.PendingIntent.getActivity(MainActivity.this, 5290,
                        new Intent(MainActivity.this, MainActivity.class), android.app.PendingIntent.FLAG_UPDATE_CURRENT | android.app.PendingIntent.FLAG_IMMUTABLE);
                android.app.Notification note = new android.app.Notification.Builder(MainActivity.this, NotificationChannels.id(kind))
                        .setSmallIcon(R.drawable.ic_notification).setContentTitle("Asteria Chat 通知检查")
                        .setContentText("这是本机显示检查，没有发送消息或联系服务器。")
                        .setContentIntent(open).setAutoCancel(true).build();
                manager.notify("texas-chat.local-check." + kind, 5290, note);
                return json("ok", true, "posted", true, "delivered", false, "local_only", true).toString();
            } catch (RuntimeException unavailable) { return json("ok", false, "error", "notification_test_unconfirmed").toString(); }
        }

        @JavascriptInterface public String openNotificationSettings() {
            if (!trusted()) return json("ok", false, "error", "local_page_required").toString();
            if (!foreground.get()) return json("ok", false, "error", "foreground_required").toString();
            try {
                NotificationManager manager = getSystemService(NotificationManager.class);
                boolean channel = manager != null && manager.getNotificationChannel(CHANNEL_ID) != null;
                Intent settings = ReplyWatchService.notificationSettingsIntent(MainActivity.this, channel);
                if (settings.resolveActivity(getPackageManager()) == null) {
                    settings = ReplyWatchService.notificationSettingsIntent(MainActivity.this, false);
                    channel = false;
                }
                if (settings.resolveActivity(getPackageManager()) == null)
                    return json("ok", false, "error", "notification_settings_unavailable").toString();
                final Intent destination = settings;
                runOnUiThread(() -> {
                    if (!trusted() || !foreground.get()) return;
                    try { startActivity(destination); }
                    catch (RuntimeException unavailable) {
                        Toast.makeText(MainActivity.this, "无法打开系统通知设置，请从手机设置中查找 Asteria Chat。", Toast.LENGTH_LONG).show();
                    }
                });
                return json("ok", true, "settings_opening", true, "target", channel ? "channel" : "app").toString();
            } catch (RuntimeException unavailable) {
                return json("ok", false, "error", "notification_settings_unavailable").toString();
            }
        }

        @JavascriptInterface public void phonePerceptionStatus(String requestId) {
            try {
                requireId(requestId);
                if (!trusted()) throw new IllegalStateException("local_page_required");
                deliverPerception(requestId, PhonePerceptionService.snapshot(MainActivity.this), null);
            } catch (Exception unavailable) {
                deliver(requestId, 400, error("perception_status_unavailable", "手机采集状态暂时无法读取。"));
            }
        }

        @JavascriptInterface public void startPhonePerception(String requestId, String sessionId, String sectionsJson) {
            try {
                requireId(requestId);
                final String session = AttachmentPolicy.session(sessionId);
                if (sectionsJson == null || sectionsJson.length() > 1024) throw new IllegalArgumentException("invalid_sections");
                final JSONObject sections = new JSONObject(sectionsJson);
                final AuthState auth = attachmentAuth();
                requirePerceptionForeground(auth);
                final long admission;
                final long serviceAdmission;
                synchronized (lock) {
                    requirePerceptionForeground(auth);
                    if (!auth.token.equals(vault.load(auth.server))) throw new IllegalStateException("saved_login_required");
                    admission = ++perceptionEpoch;
                    serviceAdmission = PhonePerceptionService.admissionGeneration();
                }
                runOnUiThread(() -> {
                    try {
                        synchronized (lock) {
                            requirePerceptionForeground(auth);
                            if (admission != perceptionEpoch || serviceAdmission != PhonePerceptionService.admissionGeneration()) {
                                deliverPerception(requestId, PhonePerceptionService.snapshot(MainActivity.this),
                                        json("start_cancelled", true, "reason", "request_superseded"));
                                return;
                            }
                            String result = PhonePerceptionService.start(MainActivity.this, auth.server, session, sections, serviceAdmission);
                            deliverPerception(requestId, result, null);
                        }
                    } catch (Exception unavailable) {
                        deliver(requestId, 400, error("perception_start_unavailable", "采集尚未启用。请确认登录、通知权限和会话登记。"));
                    }
                });
            } catch (Exception unavailable) {
                deliver(requestId, 400, error("perception_start_unavailable", "请在已登录的当前应用中明确选择采集项目。"));
            }
        }

        @JavascriptInterface public void stopPhonePerception(String requestId) {
            try {
                requireId(requestId);
                if (!trusted()) throw new IllegalStateException("local_page_required");
                synchronized (lock) {
                    ++perceptionEpoch;
                    PhonePerceptionService.stop(MainActivity.this, "user_stopped");
                    deliverPerception(requestId, PhonePerceptionService.snapshot(MainActivity.this), null);
                }
            } catch (Exception unavailable) {
                deliver(requestId, 400, error("perception_stop_unavailable", "停止结果尚未确认，请重新读取采集状态。"));
            }
        }

        @JavascriptInterface public void reportPhonePerception(String requestId) {
            try {
                requireId(requestId);
                final AuthState auth = attachmentAuth();
                synchronized (lock) {
                    requirePerceptionForeground(auth);
                    boolean queued = PhonePerceptionService.requestReport(MainActivity.this);
                    deliverPerception(requestId, PhonePerceptionService.snapshot(MainActivity.this), json("report_queued", queued));
                }
            } catch (Exception unavailable) {
                deliver(requestId, 400, error("perception_report_unavailable", "请在前台应用中先启用并确认采集，手动上报不会自动重试。"));
            }
        }

        @JavascriptInterface public void requestPhonePerceptionPermission(String requestId, String kind) {
            try {
                requireId(requestId);
                if (!("notifications".equals(kind) || "usage".equals(kind) || "music".equals(kind) || "battery".equals(kind)))
                    throw new IllegalArgumentException("invalid_permission_kind");
                final AuthState auth = attachmentAuth();
                requirePerceptionForeground(auth);
                runOnUiThread(() -> {
                    try {
                        synchronized (lock) {
                            requirePerceptionForeground(auth);
                            boolean notificationRequest = false;
                            if ("notifications".equals(kind)) {
                                notificationRequest = Build.VERSION.SDK_INT >= 33 && checkSelfPermission("android.permission.POST_NOTIFICATIONS")
                                        != android.content.pm.PackageManager.PERMISSION_GRANTED;
                                requestNotificationPermission();
                            }
                            else {
                                Intent settings = new Intent("usage".equals(kind) ? Settings.ACTION_USAGE_ACCESS_SETTINGS
                                        : "music".equals(kind) ? Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS
                                        : Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS);
                                if ("usage".equals(kind)) settings.setData(Uri.parse("package:" + getPackageName()));
                                startActivity(settings);
                            }
                            deliverPerception(requestId, PhonePerceptionService.snapshot(MainActivity.this),
                                    json("permission_kind", kind, "settings_opened", !"notifications".equals(kind),
                                            "permission_requested", notificationRequest));
                        }
                    } catch (Exception unavailable) {
                        deliver(requestId, 400, error("perception_permission_unavailable", "未能打开系统权限设置，采集开关未改变。"));
                    }
                });
            } catch (Exception unavailable) {
                deliver(requestId, 400, error("perception_permission_unavailable", "请在已登录的前台应用中打开所选系统权限。"));
            }
        }

        private void requirePerceptionForeground(AuthState auth) {
            synchronized (lock) {
                requireCurrent(auth);
                if (!foreground.get() || token == null || !token.equals(auth.token)) throw new IllegalStateException("foreground_auth_required");
            }
        }

        private void deliverPerception(String requestId, String snapshot, JSONObject additions) throws JSONException {
            JSONObject value = new JSONObject(snapshot);
            if (additions != null) for (java.util.Iterator<String> keys = additions.keys(); keys.hasNext();) {
                String key = keys.next(); value.put(key, additions.get(key));
            }
            deliver(requestId, 200, json("status", "ok", "data", value));
        }

        /* A loaded foreground history may advance only an existing watch's
           local cursor. This never starts a service or sends a message. */
        @JavascriptInterface public String ackReplyWatch(String sessionId, String serverMessageId) {
            if (!trusted() || !foreground.get()) return json("ok", false, "error", "foreground_required").toString();
            try {
                AttachmentPolicy.session(sessionId);
                if (serverMessageId == null || serverMessageId.isEmpty() || serverMessageId.length() > 160
                        || serverMessageId.indexOf('\n') >= 0 || serverMessageId.indexOf('\r') >= 0)
                    throw new IllegalArgumentException("invalid_history_id");
                AuthState auth = attachmentAuth();
                requireCurrent(auth);
                boolean updated = ReplyWatchService.acknowledge(auth.server, auth.token, sessionId, serverMessageId);
                return json("ok", updated, "history_cursor_updated", updated, "service_started", false).toString();
            } catch (RuntimeException unavailable) {
                return json("ok", false, "error", "watch_ack_unavailable", "service_started", false).toString();
            }
        }

        /* Explicit navigation to one received message only. This also works
           after the optional watch has stopped, without starting a service. */
        @JavascriptInterface public String clearMessageNotification(String sessionId, String serverMessageId) {
            if (!trusted() || !foreground.get()) return json("ok", false, "error", "foreground_required").toString();
            try {
                AttachmentPolicy.session(sessionId);
                if (serverMessageId == null || serverMessageId.isEmpty() || serverMessageId.length() > 160
                        || serverMessageId.indexOf('\n') >= 0 || serverMessageId.indexOf('\r') >= 0)
                    throw new IllegalArgumentException("invalid_history_id");
                AuthState auth = attachmentAuth();
                requireCurrent(auth);
                int cleared = ReplyWatchService.cancelMessageNotice(MainActivity.this, auth.server, auth.token, sessionId, serverMessageId);
                return json("ok", cleared >= 0, "notification_cleared", cleared > 0,
                        "notifications_cancelled", Math.max(0, cleared), "service_started", false).toString();
            } catch (RuntimeException unavailable) {
                return json("ok", false, "error", "notification_clear_unavailable", "service_started", false).toString();
            }
        }

        @JavascriptInterface public String setReplyWatch(boolean enabled, String sessionId, String title, String lastSeenAssistantServerId) {
            if (!trusted()) return json("ok", false, "error", "local_page_required").toString();
            if (!enabled) {
                synchronized (lock) {
                    if (ApiPolicy.jwt(token)) for (ReplyWatchAccounts.Record record : ReplyWatchAccounts.list(MainActivity.this)) {
                        if (record.server.equals(server) && record.username.equals(AttachmentCache.username(token))
                                && (visibleSession.isEmpty() || record.session.equals(visibleSession))) {
                            ReplyWatchService.stopTarget(MainActivity.this, record.id, "user_stopped");
                            break;
                        }
                    }
                }
                return json("ok", true, "state", "stopped", "running", false,
                        "verified_session", false, "reason", "user_stopped").toString();
            }
            try {
                AttachmentPolicy.session(sessionId);
                if (!foreground.get()) throw new IllegalStateException("foreground_required");
                if (!NotificationPreferences.load(MainActivity.this).enabled)
                    return json("ok", false, "error", "notifications_disabled", "state", "stopped", "running", false).toString();
                if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission("android.permission.POST_NOTIFICATIONS")
                        != android.content.pm.PackageManager.PERMISSION_GRANTED)
                    return json("ok", false, "error", "notification_permission", "state", "stopped", "running", false).toString();
                final AuthState auth = attachmentAuth();
                synchronized (lock) {
                    String persisted = vault.load(server);
                    if (persisted == null || !persisted.equals(auth.token))
                        throw new IllegalStateException("saved_login_required");
                }
                final String baseline = lastSeenAssistantServerId == null ? "" : lastSeenAssistantServerId;
                if (baseline.length() > 160 || baseline.indexOf('\n') >= 0 || baseline.indexOf('\r') >= 0)
                    throw new IllegalArgumentException("invalid_baseline");
                runOnUiThread(() -> {
                    try {
                        requireCurrent(auth);
                        if (!foreground.get()) throw new IllegalStateException("foreground_required");
                        ReplyWatchService.start(MainActivity.this, auth.server, auth.token, sessionId, title, baseline);
                    } catch (RuntimeException unavailable) {
                        // A failed admission must not stop another Bot.
                    }
                });
                // Starting is not a claim that Android has launched the service
                // or the server has accepted this session. Observer/status follows.
                return json("ok", true, "state", "starting", "running", false,
                        "verified_session", false, "session_id", sessionId).toString();
            } catch (RuntimeException unavailable) {
                return json("ok", false, "state", "stopped", "running", false,
                        "error", unavailable.getMessage()).toString();
            }
        }

        @JavascriptInterface public String setServer(String input) {
            if (!trusted()) return json("ok", false, "error", "local_page_required").toString();
            try {
                String next = ApiPolicy.server(input);
                synchronized (lock) {
                    if (!next.equals(server)) {
                        PhonePerceptionService.stop(MainActivity.this, "server_changed");
                        // Keep explicitly enabled accounts listening while the visible server changes.
                        epoch++;
                runOnUiThread(() -> {if(voice!=null)voice.stop();});
                        token = null;
                        vault.clear();
                        vault.server(next);
                        server = next; visibleSession = "";
                        ReplyWatchService.setVisibleAccount(server, null);
                    }
                    return json("ok", true, "server", server).toString();
                }
            } catch (RuntimeException failure) {
                return json("ok", false, "error", "invalid_or_unsaved_server").toString();
            }
        }

        @JavascriptInterface public String clearAuth() {
            if (!trusted()) return json("ok", false, "error", "local_page_required").toString();
            synchronized (lock) {
                try {
                    PhonePerceptionService.stop(MainActivity.this, "logged_out");
                    ReplyWatchService.stopAccount(MainActivity.this, server, token, "logged_out");
                } catch (RuntimeException failure) {
                    // Keep the account identity so an explicit retry can remove its saved watches.
                    return json("ok", false, "authenticated", ApiPolicy.jwt(token),
                            "error", "notification_logout_failed").toString();
                }
                epoch++;
                runOnUiThread(() -> {if(voice!=null)voice.stop();});
                token = null; visibleSession = "";
                ReplyWatchService.setVisibleAccount(server, null);
                boolean saved;
                try { saved = vault.clear(); }
                catch (RuntimeException failure) { saved = false; }
                return json("ok", saved, "authenticated", false,
                        "error", saved ? JSONObject.NULL : "persistent_logout_failed").toString();
            }
        }

        @JavascriptInterface public void requestStream(String requestId, String path, String body) {
            try {
                requireId(requestId);
                if (!("/chat/send".equals(path) || "/chat/regenerate".equals(path)))
                    throw new IllegalArgumentException("stream_route_not_allowed");
                request(json("requestId", requestId, "method", "POST", "path", path,
                        "body", new JSONObject(body), "stream", true).toString());
            } catch (Exception invalid) {
                deliver(requestId, 0, error("invalid_stream_request", "流式请求无效，未自动重新发送。"));
            }
        }

        /** Observe an existing SDK run; this entry cannot submit a message. */
        @JavascriptInterface public void requestReadStream(String requestId, String path) {
            try {
                requireId(requestId);
                if (!ApiPolicy.streamRequest("GET", path)) throw new IllegalArgumentException("stream_route_not_allowed");
                request(json("requestId", requestId, "method", "GET", "path", path,
                        "body", JSONObject.NULL, "stream", true).toString());
            } catch (Exception invalid) {
                deliver(requestId, 0, error("invalid_stream_request", "暂时无法接续回复，请同步记录。"));
            }
        }

        @JavascriptInterface public void request(String input) {
            String id = "";
            try {
                if (!trusted()) return;
                if (input == null || input.length() > MAX_REQUEST) throw new IllegalArgumentException("request_too_large");
                JSONObject request = new JSONObject(input);
                id = request.optString("requestId", "");
                if (id.isEmpty() || id.length() > 128) throw new IllegalArgumentException("invalid_request_id");
                final String requestId = id;
                final String method = ApiPolicy.method(request.optString("method", "GET"));
                final String path = ApiPolicy.requestPath(request.getString("path"));
                final boolean login = ApiPolicy.isLogin(path);
                final boolean streaming = request.optBoolean("stream", false);
                if (streaming && !ApiPolicy.streamRequest(method, path))
                    throw new IllegalArgumentException("stream_route_not_allowed");
                if (login && !method.equals("POST")) throw new IllegalArgumentException("login_requires_post");
                Object rawBody = request.opt("body");
                final byte[] body = rawBody == null || rawBody == JSONObject.NULL ? null
                        : (rawBody instanceof String ? (String) rawBody : rawBody.toString()).getBytes(StandardCharsets.UTF_8);
                if (body != null && (body.length > MAX_REQUEST || method.equals("GET")))
                    throw new IllegalArgumentException("invalid_request_body");
                final String target, bearer;
                final long generation;
                synchronized (lock) {
                    if (login) { PhonePerceptionService.stop(MainActivity.this, "authentication_changed"); /* Other saved accounts keep listening during explicit login. */ epoch++;
                runOnUiThread(() -> {if(voice!=null)voice.stop();}); token = null; vault.clear(); }
                    target = server;
                    bearer = token;
                    generation = epoch;
                }
                executor.execute(() -> perform(requestId, method, path, body, login, target, bearer, generation, streaming));
            } catch (RejectedExecutionException full) {
                deliver(id, 0, error("queue_full", "请求较多，请稍后再试。"));
            } catch (Exception invalid) {
                deliver(id, 0, error("invalid_request", "请求格式或服务地址无效。"));
            }
        }

        @JavascriptInterface public void voiceCommand(String requestId, String sessionId, String payload) {
            try {
                requireId(requestId);AttachmentPolicy.session(sessionId);final AuthState auth=attachmentAuth();
                if(payload==null||payload.length()>16000)throw new IllegalArgumentException("voice_payload");
                final JSONObject input=new JSONObject(payload); input.put("request_id",requestId);
                runOnUiThread(()->{try{requireCurrent(auth);if(voice==null)throw new IllegalStateException("voice_closed");
                    voice.command(input,auth.server+"\n"+auth.token+"\n"+sessionId,result->{try{requireCurrent(auth);deliver(requestId,200,result);}catch(Exception changed){deliver(requestId,0,error("voice_scope_changed","账户已变化，原语音操作已结束。"));}});
                }catch(Exception failure){deliver(requestId,0,error("voice_unavailable","语音操作暂不可用，请确认已登录。"));}});
            }catch(Exception failure){deliver(requestId,0,error("voice_unavailable","语音请求无效，请打开当前会话。"));}
        }
        /** Download only the authenticated TLS audio cache; no provider key enters Android. */
        @JavascriptInterface public void playCloudVoice(String requestId,String sessionId,String audioId,String messageId) {
            try {
                requireId(requestId); AttachmentPolicy.session(sessionId);
                if(audioId==null || !audioId.matches("[a-f0-9]{64}") || messageId==null || messageId.length()>200)throw new IllegalArgumentException("audio_id");
                final AuthState auth=attachmentAuth();
                final String path="/chat/voice/audio?session_id="+java.net.URLEncoder.encode(sessionId,"UTF-8")+"&audio_id="+audioId;
                runOnUiThread(()->{try{
                    requireCurrent(auth); final int ticket=voice.beginRemote(messageId,requestId);
                    submitAttachment(requestId,()->{
                        HttpURLConnection connection=null;
                        try {
                            requireCurrent(auth); long cacheGeneration=AttachmentCache.generation();
                            String key=AttachmentCache.key(auth.server,auth.token,path);
                            AttachmentCache.Entry cached=AttachmentCache.find(MainActivity.this,key);
                            if(cached==null){
                                connection=attachmentConnection(auth,path,"GET");
                                int status=connection.getResponseCode();
                                if(status!=200){attachmentUnauthorized(auth,status);throw new java.io.IOException("audio_unavailable");}
                                byte[] bytes=read(connection.getInputStream());
                                if(bytes.length<3 || bytes.length>4*1024*1024 || !(bytes[0]=='I'&&bytes[1]=='D'&&bytes[2]=='3' || (bytes[0]&255)==255&&(bytes[1]&224)==224))throw new java.io.IOException("audio_format");
                                synchronized(lock){requireCurrent(auth);ATTACHMENT_RECOVERY.admitWriter();cached=AttachmentCache.put(MainActivity.this,key,bytes,"audio/mpeg",cacheGeneration);}
                            }
                            final java.io.File file=cached.file;
                            runOnUiThread(()->{try{requireCurrent(auth);voice.remoteReady(ticket,file);deliver(requestId,200,json("ok",true,"audio_cached",true,"message_id",messageId));}catch(Exception changed){deliver(requestId,0,error("voice_scope_changed","账户已变化，语音未播放。"));}});
                        }catch(Exception failed){runOnUiThread(()->{if(voice!=null)voice.remoteFailed(ticket,"语音下载未完成，可再次播放已生成的音频。");});deliver(requestId,0,error("voice_download_failed","语音下载未完成，没有重新合成。"));}
                        finally{finishConnection(connection);}
                    });
                }catch(Exception failure){deliver(requestId,0,error("voice_unavailable","语音播放暂不可用。"));}});
            }catch(Exception failure){deliver(requestId,0,error("voice_unavailable","语音参数无效，请打开当前会话。"));}
        }
        @JavascriptInterface public void recognizeSpeech(String requestId,String sessionId,String language) {
            try {
                requireId(requestId);AttachmentPolicy.session(sessionId);
                if(!java.util.Arrays.asList("zh-CN","zh-TW","en-US","ja-JP").contains(language))throw new IllegalArgumentException("language");
                final PickerRequest selected;
                synchronized(lock){if(picker!=null)throw new IllegalStateException("picker_busy");selected=new PickerRequest(requestId,sessionId,attachmentAuth(),"recognition");picker=selected;}
                runOnUiThread(()->{try{requireCurrent(selected.auth);
                    Intent intent=new Intent(android.speech.RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
                    intent.putExtra(android.speech.RecognizerIntent.EXTRA_LANGUAGE_MODEL,android.speech.RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
                    intent.putExtra(android.speech.RecognizerIntent.EXTRA_LANGUAGE,language);
                    intent.putExtra(android.speech.RecognizerIntent.EXTRA_MAX_RESULTS,1);
                    intent.putExtra(android.speech.RecognizerIntent.EXTRA_PROMPT,"识别后加入草稿；确认后再发送。识别服务可能联网。");
                    startActivityForResult(intent,SPEECH_RECOGNIZER);
                }catch(Exception missing){synchronized(lock){if(picker==selected)picker=null;}deliver(requestId,0,error("recognizer_unavailable","手机未安装可用的系统语音识别服务，请使用键盘语音输入或录音附件。"));}});
            }catch(Exception failure){deliver(requestId,0,error("recognizer_busy","请先登录，并关闭其他文件或录音窗口。"));}
        }
        private void recognitionResult(int code,Intent data){
            final PickerRequest selected;synchronized(lock){selected=picker;if(selected==null||!"recognition".equals(selected.kind))return;picker=null;}
            try{requireCurrent(selected.auth);if(code!=RESULT_OK||data==null){deliver(selected.requestId,200,json("cancelled",true));return;}
                java.util.ArrayList<String> results=data.getStringArrayListExtra(android.speech.RecognizerIntent.EXTRA_RESULTS);
                String text=results==null||results.isEmpty()?"":results.get(0);
                if(text==null||text.trim().isEmpty()||text.length()>12000)throw new IllegalArgumentException("recognition_empty");
                deliver(selected.requestId,200,json("text",text,"session_id",selected.sessionId,"source","android_system_recognizer"));
            }catch(Exception failure){deliver(selected.requestId,0,error("recognition_failed","没有可用识别结果，草稿保持不变。"));}
        }

        /** Explicit system recording; Asteria Chat does not capture the microphone. */
        @JavascriptInterface public void recordVoice(String requestId, String sessionId) {
            try {
                requireId(requestId);
                AttachmentPolicy.session(sessionId);
                final PickerRequest selected;
                synchronized (lock) {
                    if (picker != null) throw new IllegalStateException("picker_busy");
                    selected = new PickerRequest(requestId, sessionId, attachmentAuth());
                    picker = selected;
                }
                runOnUiThread(() -> {
                    try {
                        requireCurrent(selected.auth);
                        Intent intent = new Intent(android.provider.MediaStore.Audio.Media.RECORD_SOUND_ACTION)
                                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                        startActivityForResult(intent, ATTACHMENT_PICKER);
                    } catch (Exception unavailable) {
                        synchronized (lock) { if (picker == selected) picker = null; }
                        deliver(requestId, 0, error("recorder_unavailable", "手机没有可用的系统录音应用，可从附件选择已有音频。"));
                    }
                });
            } catch (Exception unavailable) {
                deliver(requestId, 0, error("voice_not_ready", "请先连接伙伴，一次只打开一个录音或文件窗口。"));
            }
        }

        @JavascriptInterface public void chooseAttachment(String requestId, String sessionId) {
            try {
                requireId(requestId);
                AttachmentPolicy.session(sessionId);
                final PickerRequest selected;
                synchronized (lock) {
                    if (picker != null) throw new IllegalStateException("picker_busy");
                    selected = new PickerRequest(requestId, sessionId, attachmentAuth());
                    picker = selected;
                }
                launchPicker(selected, "*/*");
            } catch (Exception unavailable) {
                deliver(requestId, 0, error("attachment_not_ready", "请先登录，且一次只打开一个文件选择器。"));
            }
        }

        @JavascriptInterface public void chooseAppearanceImage(String requestId, String kind) {
            try {
                requireId(requestId);
                AppearanceImagePolicy.kind(kind);
                final PickerRequest selected;
                synchronized (lock) {
                    if (!trusted() || picker != null) throw new IllegalStateException("picker_unavailable");
                    selected = new PickerRequest(requestId, null, new AuthState(server, null, epoch), kind);
                    picker = selected;
                }
                launchPicker(selected, "image/*");
            } catch (Exception unavailable) {
                deliver(requestId, 0, error("appearance_picker_not_ready", "请在本地页面选择头像或背景，一次只打开一个选择器。"));
            }
        }


        /* Window chrome follows the page theme so dark mode is not just the
           WebView: status and navigation bars change together with it. */
        @JavascriptInterface public String setChromeTheme(String theme) {
            if (!trusted()) return json("ok", false, "error", "local_page_required").toString();
            final boolean dark = !"light".equals(theme);
            runOnUiThread(() -> {
                int bar = "black".equals(theme) ? Color.BLACK : dark ? Color.rgb(22, 26, 24) : Color.rgb(247, 248, 245);
                getWindow().setStatusBarColor(bar);
                getWindow().setNavigationBarColor(bar);
                if (viewport != null) viewport.setChromeColor(bar);
                if (Build.VERSION.SDK_INT >= 30) {
                    android.view.WindowInsetsController controller = getWindow().getInsetsController();
                    if (controller != null) {
                        int mask = android.view.WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS
                                | android.view.WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS;
                        controller.setSystemBarsAppearance(dark ? 0 : mask, mask);
                    }
                } else if (Build.VERSION.SDK_INT >= 26) {
                    android.view.View decor = getWindow().getDecorView();
                    int flags = decor.getSystemUiVisibility();
                    if (dark) {
                        flags &= ~android.view.View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR;
                        flags &= ~android.view.View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR;
                    } else {
                        flags |= android.view.View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR;
                        flags |= android.view.View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR;
                    }
                    decor.setSystemUiVisibility(flags);
                }
            });
            return json("ok", true).toString();
        }

        /* Reply notification. The page calls this only while it is hidden and
           has actually read a new server record; the server still owns delivery. */
        /* The page asks for the permission from the settings toggle, while the
           app is visible; a hidden background tick never opens a dialog. */
        @JavascriptInterface public String requestNotificationPermission() {
            if (!trusted()) return json("ok", false, "error", "local_page_required").toString();
            if (Build.VERSION.SDK_INT < 33 || checkSelfPermission("android.permission.POST_NOTIFICATIONS")
                    == android.content.pm.PackageManager.PERMISSION_GRANTED) {
                return json("ok", true, "granted", true).toString();
            }
            runOnUiThread(() -> {
                if (!trusted()) return;
                requestPermissions(new String[] { "android.permission.POST_NOTIFICATIONS" },
                        NOTIFICATION_PERMISSION);
            });
            return json("ok", true, "granted", false).toString();
        }

        /* Old pages cannot create a second notification path. */
        @JavascriptInterface public String notifyMessage(String sessionId, String title, String body) {
            if (!trusted()) return json("ok", false, "error", "local_page_required").toString();
            return json("ok", false, "error", "native_reply_watch_required").toString();
        }

        /* Bundled sticker: upload the packaged asset through the same owner-checked
           attachment endpoint, then the page sends it as one image message. */
        @JavascriptInterface public void chooseSticker(String requestId, String name, String sessionId) {
            try {
                requireId(requestId);
                AttachmentPolicy.session(sessionId);
                if (name == null || !name.matches("sticker-[0-9]{2}\\.png"))
                    throw new IllegalArgumentException("invalid_sticker");
                final PickerRequest selected;
                synchronized (lock) {
                    if (!trusted()) throw new IllegalStateException("sticker_unavailable");
                    selected = new PickerRequest(requestId, sessionId, attachmentAuth());
                }
                executor.execute(() -> uploadAsset(selected, name));
            } catch (RejectedExecutionException full) {
                deliver(requestId, 0, error("queue_full", "请求较多，请稍后再试。"));
            } catch (Exception unavailable) {
                deliver(requestId, 0, error("sticker_not_ready", "表情暂时发不出去，请先登录并打开一个对话。"));
            }
        }

        @JavascriptInterface public void exportConversation(String requestId, String filename, String markdown) {
            try {
                requireId(requestId);
                if (!trusted()) return;
                ConversationExport.Document document = ConversationExport.prepare(filename, markdown);
                final PickerRequest selected;
                synchronized (lock) {
                    if (!trusted() || picker != null) throw new IllegalStateException("picker_unavailable");
                    selected = new PickerRequest(requestId, new AuthState(server, null, epoch), document);
                    picker = selected;
                }
                runOnUiThread(() -> {
                    try {
                        requireCurrent(selected.auth);
                        Intent intent = new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE)
                                .setType("text/markdown").putExtra(Intent.EXTRA_TITLE, document.filename)
                                .addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
                        startActivityForResult(intent, ATTACHMENT_PICKER);
                    } catch (Exception unavailable) {
                        finishExport(selected, 0, json("error", "export_picker_unavailable", "message", "无法打开系统保存窗口，请稍后重试。", "partial_file_possible", false));
                    }
                });
            } catch (Exception unavailable) {
                deliver(requestId, 0, json("error", "export_not_ready", "message", "导出内容须为2 MiB以内的有效文字，且一次只能打开一个系统选择器。", "partial_file_possible", false));
            }
        }

        private void exportSelection(PickerRequest selected, int resultCode, Intent data) {
            if (resultCode != RESULT_OK || data == null || data.getData() == null) {
                finishExport(selected, 200, json("cancelled", true));
                return;
            }
            final Uri uri = data.getData();
            if (!"content".equals(uri.getScheme())) {
                finishExport(selected, 0, json("error", "invalid_export_uri", "message", "只能保存到系统窗口选定的文档。", "partial_file_possible", false));
                return;
            }
            try { executor.execute(() -> writeExport(selected, uri)); }
            catch (RejectedExecutionException full) {
                finishExport(selected, 0, json("error", "export_queue_full", "message", "当前操作较多，导出未写入；系统可能已创建空文件。", "partial_file_possible", true));
            }
        }

        private void writeExport(PickerRequest selected, Uri uri) {
            try {
                requireCurrent(selected.auth);
                try (OutputStream output = getContentResolver().openOutputStream(uri, "wt")) {
                    if (output == null) throw new java.io.IOException("export_stream_unavailable");
                    synchronized (lock) { requireCurrent(selected.auth); activeSources.add(output); }
                    try { ConversationExport.write(selected.document, output, () -> requireCurrent(selected.auth)); }
                    finally { synchronized (lock) { activeSources.remove(output); } }
                }
                requireCurrent(selected.auth);
                finishExport(selected, 200, json("exported", true, "filename", selected.document.filename, "bytes", selected.document.size()));
            } catch (Exception unavailable) {
                finishExport(selected, 0, json("error", "export_write_failed", "message", "导出未完成，所选位置可能留下空文件或部分内容；请检查后再决定是否重新导出。", "partial_file_possible", true));
            }
        }

        private void finishExport(PickerRequest selected, int status, JSONObject body) {
            runOnUiThread(() -> {
                try {
                    synchronized (lock) { requireCurrent(selected.auth); deliver(selected.requestId, status, body); }
                } catch (Exception changed) { /* A prior page/account gets no callback in the new scope. */ }
                finally { synchronized (lock) { if (picker == selected) picker = null; } }
            });
        }

        private void launchPicker(PickerRequest selected, String type) {
            runOnUiThread(() -> {
                try {
                    requireCurrent(selected.auth);
                    Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE)
                            .setType(type).putExtra(Intent.EXTRA_ALLOW_MULTIPLE, false)
                            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                    startActivityForResult(intent, ATTACHMENT_PICKER);
                } catch (Exception unavailable) {
                    synchronized (lock) { if (picker == selected) picker = null; }
                    deliver(selected.requestId, 0, error("picker_unavailable", "无法打开系统选择器，请稍后重试。"));
                }
            });
        }

        private void selectionResult(int resultCode, Intent data) {
            final PickerRequest selected;
            synchronized (lock) { selected = picker; if (selected != null && !selected.kind.equals("export")) picker = null; }
            if (selected == null) return;
            if (selected.kind.equals("export")) { exportSelection(selected, resultCode, data); return; }
            if (resultCode != RESULT_OK || data == null || data.getData() == null) {
                deliver(selected.requestId, 200, json("cancelled", true));
                return;
            }
            final Uri uri = data.getData();
            if (!"content".equals(uri.getScheme())) {
                deliver(selected.requestId, 0, error("invalid_selected_uri", "只能读取系统选择器明确选中的文件。"));
                return;
            }
            if (selected.kind.equals("attachment")) submitAttachment(selected.requestId, () -> upload(selected, uri));
            else submitAttachment(selected.requestId, () -> processAppearance(selected, uri));
        }

        private void processAppearance(PickerRequest selected, Uri uri) {
            InputStream source = null;
            try {
                requireCurrent(selected.auth);
                source = getContentResolver().openInputStream(uri);
                if (source == null) throw new java.io.IOException("appearance_source_unavailable");
                synchronized (lock) { requireCurrent(selected.auth); activeSources.add(source); }
                AppearanceBytes bytes = new AppearanceBytes();
                AttachmentStreams.copy(source, bytes, () -> requireCurrent(selected.auth));
                AppearanceImageProcessor.Result image = AppearanceImageProcessor.process(bytes.contents(), bytes.size(),
                        selected.kind, () -> requireCurrent(selected.auth));
                requireCurrent(selected.auth);
                JSONObject body = json("data_url", "data:image/jpeg;base64," + Base64.encodeToString(image.jpeg, Base64.NO_WRAP),
                        "width", image.width, "height", image.height, "kind", image.kind);
                runOnUiThread(() -> {
                    try { requireCurrent(selected.auth); deliver(selected.requestId, 200, body); }
                    catch (Exception changed) { deliver(selected.requestId, 0, error("appearance_scope_changed", "页面或账户已改变，未应用这张图片。")); }
                });
            } catch (OutOfMemoryError constrainedDevice) {
                deliver(selected.requestId, 0, error("appearance_memory_limit", "图片处理所需内存较多，请选择较小图片。"));
            } catch (Exception unavailable) {
                deliver(selected.requestId, 0, error("appearance_image_failed", "图片无法处理。请选择8 MiB以内、尺寸较小的PNG、JPEG、GIF或WebP图片。"));
            } finally {
                if (source != null) {
                    synchronized (lock) { activeSources.remove(source); }
                    try { source.close(); } catch (Exception ignored) { }
                }
            }
        }

        @JavascriptInterface public void loadAttachment(String requestId, String sessionId, String filename) {
            startDownload(requestId, sessionId, filename, true);
        }

        @JavascriptInterface public void openAttachment(String requestId, String sessionId, String filename) {
            startDownload(requestId, sessionId, filename, false);
        }

        private void startDownload(String requestId, String sessionId, String filename, boolean preview) {
            try {
                requireId(requestId);
                final String path = AttachmentPolicy.downloadPath(sessionId, filename);
                final AuthState auth = attachmentAuth();
                submitAttachment(requestId, () -> download(requestId, filename, path, auth, preview));
            } catch (Exception rejected) {
                deliver(requestId, 0, error("invalid_attachment", "附件标识或登录状态无效。"));
            }
        }

        private void submitAttachment(String id, Runnable action) {
            try { executor.execute(action); }
            catch (RejectedExecutionException full) { deliver(id, 0, error("queue_full", "请求较多，请稍后再试。")); }
        }

        private AuthState attachmentAuth() {
            synchronized (lock) {
                if (!trusted() || token == null) throw new IllegalStateException("login_required");
                return new AuthState(server, token, epoch);
            }
        }

        private void requireCurrent(AuthState auth) {
            synchronized (lock) {
                if (!trusted() || auth.epoch != epoch || !auth.server.equals(server))
                    throw new IllegalStateException("session_changed");
            }
        }

        private HttpURLConnection attachmentConnection(AuthState auth, String path, String method) throws Exception {
            requireCurrent(auth);
            HttpsURLConnection connection = (HttpsURLConnection) new URL(auth.server + ApiPolicy.requestPath(path)).openConnection();
            try {
                PinnedTls.configure(connection, auth.server);
                connection.setInstanceFollowRedirects(false);
                connection.setConnectTimeout(10000);
                connection.setReadTimeout(120000);
                connection.setRequestMethod(method);
                connection.setRequestProperty("Authorization", "Bearer " + auth.token);
                connection.setRequestProperty("User-Agent", "AsteriaChat/" + BuildConfig.VERSION_NAME);
                synchronized (lock) { requireCurrent(auth); active.add(connection); }
                return connection;
            } catch (Exception failure) { connection.disconnect(); throw failure; }
        }

        private void finishConnection(HttpURLConnection connection) {
            if (connection == null) return;
            synchronized (lock) { active.remove(connection); }
            connection.disconnect();
        }

        private void attachmentUnauthorized(AuthState auth, int status) {
            synchronized (lock) {
                requireCurrent(auth);
                if (status == 401) { PhonePerceptionService.stop(MainActivity.this, "login_expired"); ReplyWatchService.stopAccount(MainActivity.this, server, token, "login_expired"); epoch++;
                runOnUiThread(() -> {if(voice!=null)voice.stop();}); token = null; vault.clear(); }
            }
        }

        private void upload(PickerRequest selected, Uri uri) {
            HttpURLConnection connection = null;
            InputStream source = null;
            try {
                requireCurrent(selected.auth);
                String filename = "attachment.bin";
                long knownSize = -1;
                try (Cursor cursor = getContentResolver().query(uri,
                        new String[] { OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE }, null, null, null)) {
                    if (cursor != null && cursor.moveToFirst()) {
                        int nameColumn = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME);
                        int sizeColumn = cursor.getColumnIndex(OpenableColumns.SIZE);
                        if (nameColumn >= 0) filename = AttachmentPolicy.displayName(cursor.getString(nameColumn));
                        if (sizeColumn >= 0 && !cursor.isNull(sizeColumn)) knownSize = cursor.getLong(sizeColumn);
                    }
                }
                if (knownSize > AttachmentPolicy.MAX_BYTES) {
                    deliver(selected.requestId, 0, error("file_too_large", "单个附件不能超过8 MiB。"));
                    return;
                }
                String mime = AttachmentPolicy.mime(getContentResolver().getType(uri));
                source = getContentResolver().openInputStream(uri);
                if (source == null) throw new java.io.IOException("selected_file_unavailable");
                synchronized (lock) { requireCurrent(selected.auth); activeSources.add(source); }
                connection = attachmentConnection(selected.auth, "/chat/upload", "POST");
                String boundary = "AsteriaChat" + java.util.UUID.randomUUID().toString().replace("-", "");
                connection.setDoOutput(true);
                connection.setChunkedStreamingMode(64 * 1024);
                connection.setRequestProperty("Content-Type", "multipart/form-data; boundary=" + boundary);
                try (OutputStream output = connection.getOutputStream()) {
                    AttachmentStreams.multipart(output, source, boundary, selected.sessionId, filename, mime,
                            () -> requireCurrent(selected.auth));
                }
                int status = connection.getResponseCode();
                InputStream response = status >= 400 ? connection.getErrorStream() : connection.getInputStream();
                Object body = decode(new String(response == null ? new byte[0] : read(response), StandardCharsets.UTF_8),
                        connection.getContentType());
                attachmentUnauthorized(selected.auth, status);
                deliver(selected.requestId, status, body);
            } catch (Exception failure) {
                deliver(selected.requestId, 0, error("upload_not_completed", "附件上传未完成；未自动重试，请核对后重新选择。"));
            } finally {
                if (source != null) {
                    synchronized (lock) { activeSources.remove(source); }
                    try { source.close(); } catch (Exception ignored) { }
                }
                finishConnection(connection);
            }
        }

        private void uploadAsset(PickerRequest selected, String name) {
            HttpURLConnection connection = null;
            InputStream source = null;
            try {
                requireCurrent(selected.auth);
                source = getAssets().open("stickers/" + name);
                synchronized (lock) { requireCurrent(selected.auth); activeSources.add(source); }
                connection = attachmentConnection(selected.auth, "/chat/upload", "POST");
                String boundary = "AsteriaChat" + java.util.UUID.randomUUID().toString().replace("-", "");
                connection.setDoOutput(true);
                connection.setChunkedStreamingMode(64 * 1024);
                connection.setRequestProperty("Content-Type", "multipart/form-data; boundary=" + boundary);
                try (OutputStream output = connection.getOutputStream()) {
                    AttachmentStreams.multipart(output, source, boundary, selected.sessionId, name, "image/png",
                            () -> requireCurrent(selected.auth));
                }
                int status = connection.getResponseCode();
                InputStream response = status >= 400 ? connection.getErrorStream() : connection.getInputStream();
                Object body = decode(new String(response == null ? new byte[0] : read(response),
                        StandardCharsets.UTF_8), connection.getContentType());
                attachmentUnauthorized(selected.auth, status);
                deliver(selected.requestId, status, body);
            } catch (Exception failure) {
                deliver(selected.requestId, 0,
                        error("sticker_upload_not_completed", "表情上传未完成；未自动重试，请稍后再试。"));
            } finally {
                if (source != null) {
                    synchronized (lock) { activeSources.remove(source); }
                    try { source.close(); } catch (Exception ignored) { }
                }
                finishConnection(connection);
            }
        }

        private void download(String id, String filename, String path, AuthState auth, boolean preview) {
            HttpURLConnection connection = null;
            try {
                requireCurrent(auth);
                final long cacheGeneration = AttachmentCache.generation();
                String key = AttachmentCache.key(auth.server, auth.token, path);
                AttachmentCache.Entry cached = AttachmentCache.find(MainActivity.this, key);
                byte[] bytes = null;
                String mime = "application/octet-stream";
                if (cached != null) {
                    try (InputStream input = new java.io.FileInputStream(cached.file)) {
                        bytes = read(input); mime = cached.mime;
                        if (preview && (!AttachmentPolicy.previewImage(mime) || !mime.equals(AttachmentPolicy.imageSignature(bytes)))) cached = null;
                    } catch (Exception evicted) { cached = null; }
                }
                if (cached == null) {
                    connection = attachmentConnection(auth, path, "GET");
                    int status = connection.getResponseCode();
                    if (status != 200) {
                        InputStream response = status >= 400 ? connection.getErrorStream() : connection.getInputStream();
                        Object body = decode(new String(response == null ? new byte[0] : read(response), StandardCharsets.UTF_8), connection.getContentType());
                        attachmentUnauthorized(auth, status); deliver(id, status, body); return;
                    }
                    if (connection.getContentLengthLong() > AttachmentPolicy.MAX_BYTES) throw new java.io.IOException("download_too_large");
                    mime = AttachmentPolicy.mime(connection.getContentType());
                    bytes = read(connection.getInputStream());
                    requireCurrent(auth);
                    if (preview && (!AttachmentPolicy.previewImage(mime) || !mime.equals(AttachmentPolicy.imageSignature(bytes))))
                        throw new java.io.IOException("preview_type_not_allowed");
                    synchronized (lock) {
                        requireCurrent(auth); ATTACHMENT_RECOVERY.admitWriter();
                        try { cached = AttachmentCache.put(MainActivity.this, key, bytes, mime, cacheGeneration); }
                        catch (Exception cacheUnavailable) { if (!preview) throw cacheUnavailable; }
                    }
                }
                requireCurrent(auth);
                if (preview) {
                    if (!AttachmentPolicy.previewImage(mime) || !mime.equals(AttachmentPolicy.imageSignature(bytes)))
                        throw new java.io.IOException("image_signature_mismatch");
                    AttachmentPreview.Result image = AttachmentPreview.create(bytes, mime, () -> requireCurrent(auth));
                    requireCurrent(auth);
                    deliver(id, 200, json("data_url", "data:" + image.mime + ";base64," + Base64.encodeToString(image.bytes, Base64.NO_WRAP),
                            "mime_type", image.mime, "thumbnail", image.thumbnail, "width", image.width, "height", image.height));
                    return;
                }
                if (cached == null) throw new java.io.IOException("cache_unavailable");
                final Uri uri = AttachmentFileProvider.publish(MainActivity.this, cached.file, filename, mime);
                final String type = mime;
                runOnUiThread(() -> {
                    try {
                        requireCurrent(auth);
                        Intent view = new Intent(Intent.ACTION_VIEW).setDataAndType(uri, type.equals("application/octet-stream") ? "*/*" : type)
                                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                        view.setClipData(ClipData.newRawUri("Asteria Chat attachment", uri));
                        startActivity(Intent.createChooser(view, "打开附件"));
                        deliver(id, 200, json("opened", true, "viewer_confirmation", "system_chooser_dispatched"));
                    } catch (Exception unavailable) { deliver(id, 0, error("viewer_unavailable", "没有可用的应用打开此附件，或登录状态已改变。")); }
                });
            } catch (Exception failure) {
                deliver(id, 0, error(preview ? "image_preview_failed" : "attachment_download_failed", "附件暂时无法读取；仅已发送并有权访问的附件可查看。"));
            } finally { finishConnection(connection); }
        }

        private void perform(String id, String method, String path, byte[] body, boolean login,
                String target, String bearer, long generation, boolean streaming) {
            HttpURLConnection connection = null;
            try {
                synchronized (lock) {
                    if (generation != epoch || !target.equals(server) || !trusted()) {
                        deliver(id, 0, error("session_changed", "登录状态已改变，未发出请求。"));
                        return;
                    }
                }
                connection = (HttpURLConnection) new URL(target + path).openConnection();
                if (!(connection instanceof HttpsURLConnection)) throw new IllegalArgumentException("https_required");
                synchronized (lock) {
                    if (generation != epoch || !trusted()) {
                        deliver(id, 0, error("session_changed", "登录状态已改变，未发出请求。"));
                        return;
                    }
                    active.add(connection);
                }
                PinnedTls.configure((HttpsURLConnection) connection, target);
                connection.setInstanceFollowRedirects(false);
                connection.setConnectTimeout(10000);
                connection.setReadTimeout(120000);
                connection.setRequestMethod(method);
                connection.setRequestProperty("Accept", "application/json, text/event-stream");
                connection.setRequestProperty("User-Agent", "AsteriaChat/" + BuildConfig.VERSION_NAME);
                if (!login && bearer != null) connection.setRequestProperty("Authorization", "Bearer " + bearer);
                if (body != null) {
                    connection.setDoOutput(true);
                    connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
                    connection.setFixedLengthStreamingMode(body.length);
                    try (OutputStream stream = connection.getOutputStream()) { stream.write(body); }
                }
                int status = connection.getResponseCode();
                InputStream response = status >= 400 ? connection.getErrorStream() : connection.getInputStream();
                if (streaming && status >= 200 && status < 300 && response != null
                        && connection.getContentType() != null
                        && connection.getContentType().toLowerCase(java.util.Locale.ROOT).contains("text/event-stream")) {
                    StringBuilder collected = new StringBuilder();
                    try (java.io.Reader reader = new java.io.InputStreamReader(response, StandardCharsets.UTF_8)) {
                        char[] buffer = new char[2048];
                        int count;
                        while ((count = reader.read(buffer)) != -1) {
                            synchronized (lock) { requireCurrent(new AuthState(target, bearer, generation)); }
                            if (collected.length() + count > MAX_RESPONSE) throw new java.io.IOException("response_too_large");
                            String chunk = new String(buffer, 0, count);
                            collected.append(chunk);
                            final String callback = "window.AsteriaChatUI&&window.AsteriaChatUI.receiveStream("
                                    + json("id", id, "status", status, "chunk", chunk).toString() + ")";
                            runOnUiThread(() -> {
                                synchronized (lock) {
                                    if (generation != epoch || !target.equals(server) || !trusted()) return;
                                }
                                if (web != null) web.evaluateJavascript(callback, null);
                            });
                        }
                    }
                    synchronized (lock) { requireCurrent(new AuthState(target, bearer, generation)); }
                    deliver(id, status, collected.toString());
                    return;
                }
                byte[] bytes = response == null ? new byte[0] : read(response);
                String text = new String(bytes, StandardCharsets.UTF_8);
                Object result = decode(text, connection.getContentType());
                synchronized (lock) {
                    if (generation != epoch || !target.equals(server)) {
                        deliver(id, 0, error("session_changed_after_request", "请求已发出但登录状态已改变，请通过历史记录核对结果。"));
                        return;
                    }
                    if (login && status >= 200 && status < 300 && result instanceof JSONObject) {
                        String received = findToken((JSONObject) result, 0);
                        boolean persisted = false;
                        if (ApiPolicy.jwt(received)) {
                            token = received;
                            try { vault.save(target, received); persisted = true; }
                            catch (Exception unavailable) { PhonePerceptionService.stop(MainActivity.this, "authentication_unavailable"); vault.clear(); }
                            if (persisted) {
                                try { ReplyWatchService.credentialsChanged(MainActivity.this, target, received); } catch (RuntimeException unavailable) { /* Active login remains valid; background status reports its own result. */ }
                                ReplyWatchService.setVisibleAccount(target, received);
                            }
                        }
                        stripTokens(result);
                        ((JSONObject) result).put("authenticated", token != null);
                        ((JSONObject) result).put("auth_persisted", persisted);
                    } else if (status == 401) {
                        PhonePerceptionService.stop(MainActivity.this, "login_expired");
                        ReplyWatchService.stopAccount(MainActivity.this, server, token, "login_expired");
                        epoch++;
                runOnUiThread(() -> {if(voice!=null)voice.stop();});
                        token = null;
                        vault.clear();
                    }
                }
                if (login) stripTokens(result);
                deliver(id, status, result);
                if (login && status >= 200 && status < 300) runOnUiThread(MainActivity.this::dispatchPendingReply);
            } catch (Exception failure) {
                // No automatic replay: a POST can already have reached the server.
                deliver(id, 0, error("network_or_response_error", "连接未完成。请检查网络；发送结果不确定时先查看历史，避免重复发送。"));
            } finally {
                if (connection != null) {
                    synchronized (lock) { active.remove(connection); }
                    connection.disconnect();
                }
            }
        }

        private byte[] read(InputStream input) throws Exception {
            try (InputStream stream = input; ByteArrayOutputStream output = new ByteArrayOutputStream()) {
                byte[] buffer = new byte[8192];
                int length;
                while ((length = stream.read(buffer)) != -1) {
                    if (Thread.currentThread().isInterrupted()) throw new java.io.InterruptedIOException("cancelled");
                    if (output.size() + length > MAX_RESPONSE) throw new java.io.IOException("response_too_large");
                    output.write(buffer, 0, length);
                }
                return output.toByteArray();
            }
        }

        private void close() {
            synchronized (lock) {
                epoch++;
                runOnUiThread(() -> {if(voice!=null)voice.stop();});
                token = null;
                picker = null;
                for (java.io.Closeable source : activeSources) {
                    try { source.close(); } catch (Exception ignored) { }
                }
                activeSources.clear();
                for (HttpURLConnection connection : active) connection.disconnect();
                active.clear();
            }
            executor.shutdownNow();
        }
    }

    private static void requireId(String id) {
        if (id == null || id.isEmpty() || id.length() > 128) throw new IllegalArgumentException("invalid_request_id");
    }

    private void deliver(String id, int status, Object body) {
        if (id == null || id.isEmpty() || id.length() > 128) return;
        final String callback = "window.AsteriaChatUI&&window.AsteriaChatUI.receive("
                + JSONObject.quote(id) + "," + json("status", status, "body", body).toString() + ")";
        runOnUiThread(() -> { if (trusted() && web != null) web.evaluateJavascript(callback, ignored -> dispatchPendingReply()); });
    }

    private static JSONObject error(String code, String message) {
        return json("error", code, "message", message, "request_not_retried", true);
    }

    private static Object decode(String text, String contentType) {
        if (contentType != null && contentType.toLowerCase(java.util.Locale.ROOT).contains("text/event-stream")) return text;
        try { return new JSONObject(text); }
        catch (JSONException notObject) {
            try { return new JSONArray(text); }
            catch (JSONException notArray) { return text; }
        }
    }

    private static String findToken(JSONObject object, int depth) {
        if (depth > 3) return null;
        for (String key : new String[] { "token", "access_token", "accessToken" }) {
            Object value = object.opt(key);
            if (value instanceof String && ApiPolicy.jwt((String) value)) return (String) value;
        }
        Object data = object.opt("data");
        return data instanceof JSONObject ? findToken((JSONObject) data, depth + 1) : null;
    }

    private static void stripTokens(Object value) {
        if (value instanceof JSONObject) {
            JSONObject object = (JSONObject) value;
            for (String key : new String[] { "token", "access_token", "accessToken", "refresh_token", "password" }) object.remove(key);
            java.util.Iterator<String> keys = object.keys();
            while (keys.hasNext()) stripTokens(object.opt(keys.next()));
        } else if (value instanceof JSONArray) {
            JSONArray array = (JSONArray) value;
            for (int i = 0; i < array.length(); i++) stripTokens(array.opt(i));
        }
    }

    private static JSONObject json(Object... values) {
        JSONObject object = new JSONObject();
        try { for (int i = 0; i < values.length; i += 2) object.put(String.valueOf(values[i]), values[i + 1]); }
        catch (JSONException impossible) { throw new IllegalStateException("json_encoding_failed"); }
        return object;
    }
}
