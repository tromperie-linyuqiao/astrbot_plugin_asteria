package com.asteria.chat;

import android.app.ActivityManager;
import android.app.ApplicationExitInfo;
import android.content.Context;
import android.content.SharedPreferences;
import android.os.Build;
import java.util.List;
import org.json.JSONException;
import org.json.JSONObject;

/** Bounded local metadata only: no message, credential, trace or free-form exception text. */
final class ReplyWatchDiagnostics {
    private static final String KEY = "diagnosis_accounts_v1";
    private static final int MAX_ROWS = 12; // At most six registered and six recent stopped targets.

    private ReplyWatchDiagnostics() {}

    static synchronized void attempt(SharedPreferences saved, String scope) {
        change(saved, scope, "last_attempt_at", System.currentTimeMillis(), "read_reason", JSONObject.NULL);
    }

    static synchronized void success(SharedPreferences saved, String scope) {
        change(saved, scope, "last_success_at", System.currentTimeMillis(), "last_error", JSONObject.NULL);
    }

    static synchronized void readReason(SharedPreferences saved, String scope, String reason) {
        change(saved, scope, "read_reason", readCode(reason), null, null);
    }

    static synchronized void error(SharedPreferences saved, String scope, String reason) {
        change(saved, scope, "last_error", errorCode(reason), null, null);
    }

    static synchronized void notice(SharedPreferences saved, String scope, String state) {
        boolean posted = "posted".equals(state);
        change(saved, scope, "last_notice_outcome", posted ? "posted" : "posting_unknown",
                posted ? "last_notice_posted_at" : null, posted ? System.currentTimeMillis() : null);
    }

    static synchronized void stopped(SharedPreferences saved, String scope, String reason) {
        change(saved, scope, "stopped_at", System.currentTimeMillis(), "stop_reason", stopCode(reason));
    }

    static synchronized JSONObject account(SharedPreferences saved, String scope) throws JSONException {
        JSONObject row = rows(saved).optJSONObject(scope);
        if (row == null) row = new JSONObject();
        Object outcome = row.opt("last_notice_outcome");
        long postedAt = row.optLong("last_notice_posted_at");
        // The existing synchronous pre/post-call journal remains authoritative
        // even if the process ended before a later diagnostic apply reached disk.
        try {
            JSONObject notices = new JSONObject(saved.getString("notice_dispositions_" + scope, "{}"));
            long latestAt = -1;
            for (java.util.Iterator<String> keys = notices.keys(); keys.hasNext();) {
                JSONObject notice = notices.optJSONObject(keys.next());
                if (notice == null) continue;
                long at = notice.optLong("at");
                boolean posted = "posted".equals(notice.optString("state"));
                if (posted) postedAt = Math.max(postedAt, at);
                if (at > latestAt || (at == latestAt && !posted)) {
                    latestAt = at; outcome = posted ? "posted" : "posting_unknown";
                }
            }
        } catch (JSONException invalid) { outcome = "posting_unknown"; }
        return new JSONObject().put("last_attempt_at", timestamp(row.optLong("last_attempt_at")))
                .put("last_success_at", timestamp(row.optLong("last_success_at")))
                .put("last_notice_posted_at", timestamp(postedAt))
                .put("last_notice_outcome", "posted".equals(outcome) || "posting_unknown".equals(outcome) ? outcome : JSONObject.NULL)
                .put("last_error", errorCode(row.optString("last_error")))
                .put("read_reason", readCode(row.optString("read_reason")))
                .put("stopped_at", timestamp(row.optLong("stopped_at", saved.getLong("stop_at_" + scope, 0))))
                .put("stop_reason", stopCode(row.optString("stop_reason", saved.getString("stop_reason_" + scope, ""))));
    }

    static JSONObject system(Context context) throws JSONException {
        String reason = "unknown";
        long at = 0;
        if (Build.VERSION.SDK_INT >= 30) try {
            ActivityManager manager = context.getSystemService(ActivityManager.class);
            // Own package only, a small result limit, no trace, description or process metadata.
            List<ApplicationExitInfo> exits = manager == null ? null
                    : manager.getHistoricalProcessExitReasons(context.getPackageName(), 0, 1);
            if (exits != null && !exits.isEmpty()) {
                ApplicationExitInfo exit = exits.get(0);
                reason = exitCode(exit.getReason());
                at = exit.getTimestamp();
            }
        } catch (RuntimeException unavailable) { /* Unknown is different from proof of a clean exit. */ }
        return new JSONObject().put("schema", 1).put("last_exit", new JSONObject()
                .put("reason", reason).put("timestamp", timestamp(at)));
    }

    private static Object timestamp(long value) { return value > 0 ? value : JSONObject.NULL; }

    private static Object readCode(String value) {
        return "foreground_ui_owns_reads".equals(value) || "cursor_unavailable_open_chat".equals(value)
                ? value : JSONObject.NULL;
    }

    private static Object errorCode(String value) {
        return "network_or_history_unavailable".equals(value) || "local_delivery_state_unavailable".equals(value)
                ? value : JSONObject.NULL;
    }

    private static Object stopCode(String value) {
        if (value == null || value.isEmpty() || "null".equals(value)) return JSONObject.NULL;
        switch (value) {
            case "user_stopped": case "notifications_disabled": case "notification_permission":
            case "not_enabled": case "notifications_not_enabled": case "system_time_limit":
            case "service_destroyed": case "foreground_start_not_allowed": case "watch_start_unavailable":
            case "restart_registration_unavailable": case "watch_stopped": case "session_unavailable":
            case "authentication_changed": case "logged_out": case "server_changed":
            case "login_expired": case "login_required": return value;
            default: return "unknown";
        }
    }

    private static String exitCode(int value) {
        switch (value) {
            case 1: return "exit_self"; case 2: return "signaled"; case 3: return "low_memory";
            case 4: return "crash"; case 5: return "crash_native"; case 6: return "anr";
            case 7: return "initialization_failure"; case 8: return "permission_change";
            case 9: return "excessive_resource_usage"; case 10: return "user_requested";
            case 11: return "user_stopped"; case 12: return "dependency_died"; case 13: return "other";
            case 14: return "freezer"; case 15: return "package_state_change"; case 16: return "package_updated";
            default: return "unknown";
        }
    }

    private static JSONObject rows(SharedPreferences saved) {
        try { return new JSONObject(saved.getString(KEY, "{}")); }
        catch (JSONException invalid) { return new JSONObject(); }
    }

    private static void change(SharedPreferences saved, String scope, String field, Object value,
                               String extraField, Object extraValue) {
        if (saved == null || scope == null || scope.isEmpty()) return;
        try {
            JSONObject rows = rows(saved), row = rows.optJSONObject(scope);
            if (row == null) row = new JSONObject();
            if (value.equals(row.opt(field)) && (extraField == null || extraValue.equals(row.opt(extraField)))) return;
            row.put(field, value);
            if (extraField != null) row.put(extraField, extraValue);
            row.put("updated_at", System.currentTimeMillis());
            rows.put(scope, row);
            while (rows.length() > MAX_ROWS) {
                String oldest = null; long at = Long.MAX_VALUE;
                for (java.util.Iterator<String> keys = rows.keys(); keys.hasNext();) {
                    String key = keys.next(); JSONObject candidate = rows.optJSONObject(key);
                    long updated = candidate == null ? 0 : candidate.optLong("updated_at");
                    if (!scope.equals(key) && updated < at) { oldest = key; at = updated; }
                }
                if (oldest == null) break;
                rows.remove(oldest);
            }
            saved.edit().putString(KEY, rows.toString()).apply();
        } catch (JSONException unavailable) { /* Diagnostics never change delivery admission. */ }
    }
}
