package com.asteria.chat;

import android.graphics.Insets;
import android.graphics.Rect;
import android.os.Build;
import android.view.View;
import android.view.ViewTreeObserver;
import android.view.Window;
import android.view.WindowInsets;
import android.view.WindowManager;
import android.webkit.WebView;
import android.widget.FrameLayout;
import org.json.JSONException;
import org.json.JSONObject;

/** Owns the native visible rectangle. The page must not subtract IME twice. */
final class ChatViewportController {
    interface Sink { void changed(String metrics); }

    private final Window window;
    private final FrameLayout container;
    private final WebView web;
    private final Sink sink;
    private final float density;
    private final Rect visibleFrame = new Rect();
    private boolean closed, queued, imeVisible;
    private int imeHeight, systemTop, systemBottom;
    private int previousWidth = -1, previousHeight = -1;
    private int previousIme = -1, previousTop = -1, previousBottom = -1;
    private boolean previousImeVisible;
    private long sequence;
    private boolean forceNext;
    private volatile String latest = "{}";

    private final View.OnLayoutChangeListener layoutListener =
            (view, left, top, right, bottom, oldLeft, oldTop, oldRight, oldBottom) -> schedule(false);
    private final ViewTreeObserver.OnGlobalLayoutListener legacyListener = this::readLegacyViewport;
    private final Runnable publishFrame = this::publish;

    ChatViewportController(Window window, FrameLayout container, WebView web, Sink sink) {
        this.window = window;
        this.container = container;
        this.web = web;
        this.sink = sink;
        density = Math.max(0.1f, web.getResources().getDisplayMetrics().density);
    }

    void attach() {
        window.setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
        if (Build.VERSION.SDK_INT >= 30) {
            // Target 35 uses edge-to-edge. The same explicit policy on 30–34
            // keeps bars and keyboard under a single native owner.
            window.setDecorFitsSystemWindows(false);
            container.setOnApplyWindowInsetsListener((view, insets) -> {
                // Commit the settled rectangle once. Resizing the WebView and
                // evaluating JS on every IME animation frame forces expensive
                // transcript reflows and fights the system keyboard animation.
                applyInsets(insets);
                return WindowInsets.CONSUMED;
            });
            container.requestApplyInsets();
        } else {
            // On 26–29 the window already fits system bars and adjustResize
            // shrinks its content for IME. Adding IME padding here would shrink twice.
            container.getViewTreeObserver().addOnGlobalLayoutListener(legacyListener);
        }
        container.addOnLayoutChangeListener(layoutListener);
        web.addOnLayoutChangeListener(layoutListener);
        schedule(true);
    }

    private void applyInsets(WindowInsets insets) {
        if (closed || Build.VERSION.SDK_INT < 30) return;
        Insets bars = insets.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout());
        Insets keyboard = insets.getInsets(WindowInsets.Type.ime());
        imeVisible = insets.isVisible(WindowInsets.Type.ime());
        imeHeight = imeVisible ? keyboard.bottom : 0;
        systemTop = bars.top;
        systemBottom = bars.bottom;
        int bottom = Math.max(bars.bottom, imeHeight);
        if (container.getPaddingLeft() != bars.left || container.getPaddingTop() != bars.top
                || container.getPaddingRight() != bars.right || container.getPaddingBottom() != bottom) {
            container.setPadding(bars.left, bars.top, bars.right, bottom);
        }
        schedule(false);
    }

    private void readLegacyViewport() {
        if (closed) return;
        container.getWindowVisibleDisplayFrame(visibleFrame);
        int fullHeight = container.getRootView().getHeight();
        int covered = Math.max(0, fullHeight - visibleFrame.bottom);
        // Floating keyboards do not resize content; they must not manufacture
        // an inset from a navigation bar or a small system overlay.
        imeVisible = covered > Math.max(Math.round(80 * density), fullHeight / 5);
        imeHeight = imeVisible ? covered : 0;
        systemTop = Math.max(0, visibleFrame.top);
        systemBottom = imeVisible ? 0 : covered;
        schedule(false);
    }

    void refresh() {
        if (closed) return;
        if (Build.VERSION.SDK_INT >= 30) container.requestApplyInsets();
        else readLegacyViewport();
        schedule(true);
    }

    String snapshot() { return latest; }

    void setChromeColor(int color) { container.setBackgroundColor(color); }

    private void schedule(boolean force) {
        if (closed) return;
        forceNext |= force;
        if (queued) return;
        queued = true;
        web.postOnAnimation(publishFrame);
    }

    private void publish() {
        queued = false;
        if (closed) return;
        int width = web.getWidth(), height = web.getHeight();
        if (width <= 0 || height <= 0) return;
        if (!forceNext && width == previousWidth && height == previousHeight
                && imeHeight == previousIme && imeVisible == previousImeVisible
                && systemTop == previousTop && systemBottom == previousBottom) return;
        forceNext = false;
        previousWidth = width; previousHeight = height;
        previousIme = imeHeight; previousImeVisible = imeVisible;
        previousTop = systemTop; previousBottom = systemBottom;
        JSONObject data = new JSONObject();
        try {
            data.put("source", "android");
            data.put("height", Math.round(height / density));
            data.put("width", Math.round(width / density));
            data.put("imeVisible", imeVisible);
            data.put("imeHeight", Math.round(imeHeight / density));
            data.put("systemTop", Math.round(systemTop / density));
            data.put("systemBottom", Math.round(systemBottom / density));
            data.put("contentInsetsApplied", Build.VERSION.SDK_INT >= 30);
            data.put("sequence", ++sequence);
        } catch (JSONException invalid) { return; }
        latest = data.toString();
        sink.changed(latest);
    }

    void close() {
        if (closed) return;
        closed = true;
        web.removeCallbacks(publishFrame);
        web.removeOnLayoutChangeListener(layoutListener);
        container.removeOnLayoutChangeListener(layoutListener);
        ViewTreeObserver observer = container.getViewTreeObserver();
        if (observer.isAlive()) observer.removeOnGlobalLayoutListener(legacyListener);
        if (Build.VERSION.SDK_INT >= 30) {
            container.setOnApplyWindowInsetsListener(null);
        }
    }
}
