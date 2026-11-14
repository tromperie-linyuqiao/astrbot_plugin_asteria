package com.asteria.chat;

import android.app.KeyguardManager;
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
import android.content.res.Configuration;
import android.graphics.Color;
import android.graphics.PixelFormat;
import android.graphics.Rect;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.PowerManager;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewConfiguration;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import java.util.UUID;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

/** An optional, local overlay. Network reads and conversation navigation remain owned by Chat. */
public final class MobilePetService extends Service {
    static final int COMPANION = 0, GAME = 1, FOLLOW = 2;
    private static final int NOTIFICATION_ID = 47821;
    private static final String CHANNEL = "mobile_pet_controls";
    private static final String START = "mobile_pet.start", STOP = "mobile_pet.stop";
    private static final String TICKET = "mobile_pet_ticket";
    private static volatile Binding request;
    private static volatile MobilePetService active;
    private static volatile boolean appVisible;

    private static final class Binding {
        final String scope, server, session, ticket = UUID.randomUUID().toString();
        Binding(String scope, String server, String session) {
            this.scope = scope; this.server = server; this.session = session;
        }
    }

    private final Handler main = new Handler(Looper.getMainLooper());
    private final BroadcastReceiver screen = new BroadcastReceiver() {
        @Override public void onReceive(Context context, Intent intent) {
            if (Intent.ACTION_SCREEN_OFF.equals(intent.getAction())) {
                observedGame = false;
                expanded = false;
                removeWindow();
            } else updateWindow();
        }
    };
    private volatile Binding binding;
    private WindowManager windows;
    private WindowManager.LayoutParams layout;
    private LinearLayout bubble;
    private ScheduledExecutorService foregroundCheck;
    private int mode;
    private String gamePackage, replyId = "";
    private boolean observedGame, expanded;
    private float anchorX, anchorY;

    static SharedPreferences settings(Context context) {
        return context.getSharedPreferences("asteria_mobile_pet", MODE_PRIVATE);
    }

    static boolean canDraw(Context context) {
        return android.provider.Settings.canDrawOverlays(context);
    }

    static boolean notificationAvailable(Context context) {
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        if (manager == null || !manager.areNotificationsEnabled()) return false;
        NotificationChannel channel = manager.getNotificationChannel(CHANNEL);
        return channel == null || channel.getImportance() != NotificationManager.IMPORTANCE_NONE;
    }

    static void start(Context context, String scope, String server, String session) {
        Binding next = new Binding(scope, server, session);
        request = next;
        try {
            context.startForegroundService(new Intent(context, MobilePetService.class)
                    .setAction(START).putExtra(TICKET, next.ticket));
        } catch (RuntimeException failure) {
            request = null;
            throw failure;
        }
    }

    static void stop(Context context) {
        if (request == null && active == null) return;
        request = null;
        context.stopService(new Intent(context, MobilePetService.class));
    }

    static void keepOnly(Context context, String scope) {
        Binding selected = request;
        if (selected != null && !selected.scope.equals(scope)) stop(context);
    }

    static boolean enabled(String scope) {
        MobilePetService service = active;
        Binding selected = request;
        return service != null && service.binding == selected && selected != null && selected.scope.equals(scope);
    }

    static boolean requested(String scope) {
        Binding selected = request;
        return selected != null && selected.scope.equals(scope);
    }

    static boolean petIntent(Intent intent) {
        return intent != null && intent.hasExtra(TICKET);
    }

    static boolean ownsIntent(Intent intent) {
        Binding selected = request;
        return selected != null && selected.ticket.equals(intent.getStringExtra(TICKET))
                && selected.scope.equals(intent.getStringExtra("reply_watch_scope"))
                && selected.session.equals(intent.getStringExtra("session_id"));
    }

    static void appVisibility(boolean visible) {
        appVisible = visible;
        MobilePetService service = active;
        if (service != null) service.main.post(() -> {
            if (visible) service.expanded = false;
            service.updateWindow();
        });
    }

    static void onReply(String scope, String id) {
        MobilePetService service = active;
        Binding selected = request;
        if (service == null || selected == null || !selected.scope.equals(scope)) return;
        service.main.post(() -> {
            if (service.binding != selected || request != selected || service.replyId.equals(id)) return;
            service.replyId = id;
            service.updateWindow();
        });
    }

    @Override public void onCreate() {
        super.onCreate();
        windows = getSystemService(WindowManager.class);
        IntentFilter filter = new IntentFilter(Intent.ACTION_SCREEN_OFF);
        filter.addAction(Intent.ACTION_SCREEN_ON);
        filter.addAction(Intent.ACTION_USER_PRESENT);
        if (Build.VERSION.SDK_INT >= 33) registerReceiver(screen, filter, RECEIVER_NOT_EXPORTED);
        else registerReceiver(screen, filter);
    }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        Binding selected = request;
        String ticket = intent == null ? "" : intent.getStringExtra(TICKET);
        if (intent != null && STOP.equals(intent.getAction())) {
            if (selected != null && selected.ticket.equals(ticket)) {
                request = null;
                stopSelf();
            }
            return START_NOT_STICKY;
        }
        if (selected == null) { stopSelf(startId); return START_NOT_STICKY; }
        if (intent == null || !START.equals(intent.getAction()) || !selected.ticket.equals(ticket)) return START_NOT_STICKY;
        if (!canDraw(this) || !notificationAvailable(this) || windows == null) {
            request = null;
            stopSelf(startId);
            return START_NOT_STICKY;
        }
        try {
            if (binding == null || !binding.scope.equals(selected.scope)) replyId = "";
            binding = selected;
            observedGame = false;
            expanded = false;
            SharedPreferences prefs = settings(this);
            anchorX = prefs.getFloat("x", 1f);
            anchorY = prefs.getFloat("y", .66f);
            mode = prefs.getInt("mode", COMPANION);
            gamePackage = prefs.getString("game_package", "");
            startForeground(NOTIFICATION_ID, notification());
            active = this;
            watchForeground();
            updateWindow();
        } catch (RuntimeException unavailable) {
            if (request == selected) request = null;
            stopSelf(startId);
        }
        return START_NOT_STICKY;
    }

    private Notification notification() {
        NotificationManager manager = getSystemService(NotificationManager.class);
        NotificationChannel channel = new NotificationChannel(CHANNEL, "手机桌宠", NotificationManager.IMPORTANCE_LOW);
        channel.setShowBadge(false);
        manager.createNotificationChannel(channel);
        Intent stop = new Intent(this, MobilePetService.class).setAction(STOP).putExtra(TICKET, binding.ticket);
        int flags = PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE;
        return new Notification.Builder(this, CHANNEL).setSmallIcon(R.drawable.ic_notification)
                .setContentTitle(getString(R.string.app_name) + " 手机桌宠")
                .setContentText("轻触回到绑定会话").setOngoing(true).setOnlyAlertOnce(true).setShowWhen(false)
                .setContentIntent(PendingIntent.getActivity(this, NOTIFICATION_ID, openIntent(""), flags))
                .addAction(0, "关闭桌宠", PendingIntent.getService(this, NOTIFICATION_ID, stop, flags))
                .build();
    }

    private Intent openIntent(String id) {
        return new Intent(this, MainActivity.class)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP | Intent.FLAG_ACTIVITY_CLEAR_TOP)
                .putExtra(TICKET, binding.ticket).putExtra("reply_watch_scope", binding.scope)
                .putExtra("reply_watch_server", binding.server).putExtra("session_id", binding.session)
                .putExtra("reply_message_id", id).putExtra("reply_click_target", id.isEmpty() ? "conversation" : "message");
    }

    private void openChat() {
        if (binding == null || request != binding) return;
        try {
            startActivity(openIntent(replyId));
            expanded = false;
            replyId = "";
            updateWindow();
        } catch (RuntimeException unavailable) {
            // The persistent control notification provides a second user-initiated entry.
        }
    }

    private void watchForeground() {
        if (foregroundCheck != null) foregroundCheck.shutdownNow();
        if (mode != FOLLOW) return;
        Binding selected = binding;
        String target = gamePackage;
        foregroundCheck = Executors.newSingleThreadScheduledExecutor();
        foregroundCheck.scheduleWithFixedDelay(() -> {
            boolean match = request == selected && !appVisible && screenAvailable()
                    && PhonePerceptionCollector.isForegroundPackage(this, target);
            main.post(() -> {
                if (request != selected || binding != selected || mode != FOLLOW || observedGame == match) return;
                observedGame = match;
                expanded = false;
                updateWindow();
            });
        }, 0, 15, TimeUnit.SECONDS);
    }

    private boolean screenAvailable() {
        PowerManager power = getSystemService(PowerManager.class);
        KeyguardManager keyguard = getSystemService(KeyguardManager.class);
        return power != null && power.isInteractive() && keyguard != null && !keyguard.isKeyguardLocked();
    }

    private boolean game() { return mode == GAME || mode == FOLLOW && observedGame; }

    private void switchGame() {
        mode = game() ? COMPANION : GAME;
        observedGame = false;
        settings(this).edit().putInt("mode", mode).apply();
        watchForeground();
        expanded = false;
        updateWindow();
    }

    private void updateWindow() {
        if (binding == null || binding != request || appVisible || !screenAvailable()) {
            removeWindow();
            return;
        }
        if (!canDraw(this)) { stop(this); return; }
        if (bubble != null && layout != null && Boolean.TRUE.equals(bubble.getTag()) == expanded) {
            render();
            place();
            return;
        }
        removeWindow();
        bubble = new LinearLayout(this);
        bubble.setTag(expanded);
        bubble.setOrientation(LinearLayout.VERTICAL);
        bubble.setGravity(Gravity.CENTER);
        bubble.setPadding(dp(4), dp(4), dp(4), dp(4));
        layout = new WindowManager.LayoutParams(0, 0, WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE | WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
                PixelFormat.TRANSLUCENT);
        layout.gravity = Gravity.TOP | Gravity.LEFT;
        if (Build.VERSION.SDK_INT >= 30) layout.setFitInsetsTypes(0);
        render();
        measurePosition();
        try { windows.addView(bubble, layout); }
        catch (RuntimeException unavailable) { bubble = null; layout = null; stop(this); }
    }

    private void render() {
        bubble.removeAllViews();
        if (expanded) {
            bubble.setBackground(background(0xff15181e, 16));
            ScrollView scroll = new ScrollView(this);
            scroll.setFillViewport(true);
            LinearLayout controls = new LinearLayout(this);
            controls.setOrientation(LinearLayout.VERTICAL);
            scroll.addView(controls);
            bubble.addView(scroll, new LinearLayout.LayoutParams(-1, -1));
            TextView title = new TextView(this);
            title.setText(game() ? "游戏模式" : replyId.isEmpty() ? "手机桌宠" : "有新回复");
            title.setTextColor(Color.WHITE);
            title.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
            title.setGravity(Gravity.CENTER);
            controls.addView(title, new LinearLayout.LayoutParams(-1, dp(28)));
            addAction(controls, "打开聊天", this::openChat);
            addAction(controls, game() ? "退出游戏模式" : "开启游戏模式", this::switchGame);
            addAction(controls, "收起", () -> { expanded = false; updateWindow(); });
            addAction(controls, "关闭桌宠", () -> stop(this));
            return;
        }
        bubble.setBackground(null);
        ImageView image = new ImageView(this);
        image.setScaleType(ImageView.ScaleType.FIT_CENTER);
        NotificationIdentity identity = NotificationIdentity.load(this, binding.scope, "");
        android.graphics.Bitmap avatar = identity.portrait();
        if (avatar == null) image.setImageResource(R.mipmap.ic_launcher); else image.setImageBitmap(avatar);
        image.setContentDescription(replyId.isEmpty() ? "手机桌宠，轻触打开操作" : "有新回复，轻触打开操作");
        bubble.addView(image, new LinearLayout.LayoutParams(-1, dp(game() ? 42 : 64)));
        if (!replyId.isEmpty()) {
            TextView hint = new TextView(this);
            hint.setText(game() ? "●" : "●  新回复");
            hint.setTextColor(game() ? 0xffb2bfe7 : Color.WHITE);
            hint.setTextSize(11);
            hint.setGravity(Gravity.CENTER);
            if (!game()) hint.setBackground(background(0xff202632, 9));
            hint.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
            bubble.addView(hint, new LinearLayout.LayoutParams(-1, dp(18)));
        }
        image.setOnClickListener(view -> { expanded = true; updateWindow(); });
        image.setOnTouchListener(new View.OnTouchListener() {
            private float downX, downY;
            private int startX, startY;
            private boolean dragged;
            @Override public boolean onTouch(View view, MotionEvent event) {
                switch (event.getActionMasked()) {
                    case MotionEvent.ACTION_DOWN:
                        downX = event.getRawX(); downY = event.getRawY();
                        startX = layout.x; startY = layout.y; dragged = false;
                        return true;
                    case MotionEvent.ACTION_MOVE:
                        float dx = event.getRawX() - downX, dy = event.getRawY() - downY;
                        int threshold = ViewConfiguration.get(MobilePetService.this).getScaledTouchSlop();
                        if (Math.abs(dx) > threshold || Math.abs(dy) > threshold) dragged = true;
                        if (dragged && !game()) {
                            Rect field = field();
                            int spanX = Math.max(1, field.width() - layout.width);
                            int spanY = Math.max(1, field.height() - layout.height);
                            anchorX = clamp((startX + dx - field.left) / spanX);
                            anchorY = clamp((startY + dy - field.top) / spanY);
                            place();
                        }
                        return true;
                    case MotionEvent.ACTION_UP:
                        if (!dragged) view.performClick();
                        else if (!game()) settings(MobilePetService.this).edit().putFloat("x", anchorX).putFloat("y", anchorY).apply();
                        return true;
                    default: return true;
                }
            }
        });
    }

    private void addAction(LinearLayout controls, String text, Runnable action) {
        Button button = new Button(this);
        button.setText(text);
        button.setTextSize(14);
        button.setAllCaps(false);
        button.setTextColor(Color.WHITE);
        button.setOnClickListener(view -> action.run());
        controls.addView(button, new LinearLayout.LayoutParams(-1, dp(48)));
    }

    private GradientDrawable background(int color, int radius) {
        GradientDrawable drawable = new GradientDrawable();
        drawable.setColor(color);
        drawable.setCornerRadius(dp(radius));
        return drawable;
    }

    private Rect field() {
        if (Build.VERSION.SDK_INT >= 30) {
            android.view.WindowMetrics metrics = windows.getCurrentWindowMetrics();
            Rect bounds = new Rect(metrics.getBounds());
            android.graphics.Insets insets = metrics.getWindowInsets().getInsetsIgnoringVisibility(
                    android.view.WindowInsets.Type.systemBars() | android.view.WindowInsets.Type.displayCutout());
            bounds.left += insets.left; bounds.top += insets.top;
            bounds.right -= insets.right; bounds.bottom -= insets.bottom;
            return bounds;
        }
        android.util.DisplayMetrics metrics = new android.util.DisplayMetrics();
        windows.getDefaultDisplay().getMetrics(metrics);
        return new Rect(0, 0, metrics.widthPixels, metrics.heightPixels);
    }

    private void measurePosition() {
        Rect field = field();
        int desiredWidth = dp(expanded ? 168 : game() ? 56 : 94);
        int desiredHeight = dp(expanded ? 228 : (game() ? 50 : 72) + (replyId.isEmpty() ? 0 : 18));
        layout.width = Math.max(1, Math.min(field.width(), desiredWidth));
        layout.height = Math.max(1, Math.min(field.height(), desiredHeight));
        layout.x = field.left + Math.round(clamp(anchorX) * (field.width() - layout.width));
        layout.y = field.top + Math.round(clamp(anchorY) * (field.height() - layout.height));
    }

    private static float clamp(float value) { return Math.max(0f, Math.min(1f, value)); }
    private int dp(int value) { return Math.round(value * getResources().getDisplayMetrics().density); }
    private void place() {
        if (bubble == null || layout == null) return;
        measurePosition();
        try { windows.updateViewLayout(bubble, layout); }
        catch (RuntimeException unavailable) { stop(this); }
    }

    private void removeWindow() {
        if (bubble != null && bubble.isAttachedToWindow()) windows.removeViewImmediate(bubble);
        bubble = null;
        layout = null;
    }

    @Override public void onConfigurationChanged(Configuration config) {
        super.onConfigurationChanged(config);
        place();
    }

    @Override public void onDestroy() {
        if (active == this) active = null;
        if (request == binding) request = null;
        if (foregroundCheck != null) foregroundCheck.shutdownNow();
        main.removeCallbacksAndMessages(null);
        unregisterReceiver(screen);
        removeWindow();
        stopForeground(STOP_FOREGROUND_REMOVE);
        super.onDestroy();
    }

    @Override public IBinder onBind(Intent intent) { return null; }
}
