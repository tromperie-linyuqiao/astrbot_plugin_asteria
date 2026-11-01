package com.asteria.chat;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;
import org.json.JSONObject;

/** Native-only credentials for explicitly enabled watches; never serialize these records to JS/Intents. */
final class ReplyWatchAccounts {
    private static final String PREFS = "asteria_chat_reply_watch_accounts_v1";
    private static final String ALIAS = "asteria_chat_reply_watch_accounts_v1";
    private static final String PREFIX = "record:";
    private static final Object LOCK = new Object();
    private static final int MAX_RECORDS = 6;
    private static final int MAX_PLAIN_BYTES = 80000;
    private static final int MAX_ENVELOPE_CHARS = 110000;

    private ReplyWatchAccounts() { }

    static final class Record {
        final String id, server, token, session, title, baseline, username;
        private Record(String id, String server, String token, String session, String title, String baseline, String username) {
            this.id = id; this.server = server; this.token = token; this.session = session;
            this.title = title; this.baseline = baseline; this.username = username;
        }
    }

    static List<Record> list(Context context) {
        synchronized (LOCK) {
            SharedPreferences prefs = prefs(context);
            List<Record> result = new ArrayList<>();
            for (String id : ids(prefs)) {
                Record row = read(prefs, id);
                if (row != null) result.add(row);
                if (result.size() == MAX_RECORDS) break;
            }
            return Collections.unmodifiableList(result);
        }
    }

    static Record find(Context context, String id) {
        synchronized (LOCK) { return validId(id) ? read(prefs(context), id) : null; }
    }

    /** Caller supplies a JWT obtained from an authenticated login, not an arbitrary web payload. */
    static Record save(Context context, String server, String token, String session, String title, String baseline) {
        synchronized (LOCK) {
            Record row = record(server, token, session, title, baseline);
            SharedPreferences prefs = prefs(context);
            List<String> savedIds = ids(prefs);
            if (!savedIds.contains(row.id) && savedIds.size() >= MAX_RECORDS)
                throw new IllegalStateException("watch_account_limit");
            try {
                JSONObject data = new JSONObject().put("id", row.id).put("server", row.server)
                        .put("token", row.token).put("session", row.session).put("title", row.title)
                        .put("baseline", row.baseline).put("username", row.username);
                byte[] plain = data.toString().getBytes(StandardCharsets.UTF_8);
                if (plain.length > MAX_PLAIN_BYTES) throw new IllegalArgumentException("watch_record_too_large");
                Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
                cipher.init(Cipher.ENCRYPT_MODE, key(true));
                cipher.updateAAD(aad(row.id));
                JSONObject envelope = new JSONObject().put("v", 1)
                        .put("iv", Base64.encodeToString(cipher.getIV(), Base64.NO_WRAP))
                        .put("ciphertext", Base64.encodeToString(cipher.doFinal(plain), Base64.NO_WRAP));
                String encoded = envelope.toString();
                if (encoded.length() > MAX_ENVELOPE_CHARS) throw new IllegalArgumentException("watch_record_too_large");
                if (!prefs.edit().putString(PREFIX + row.id, encoded).commit())
                    throw new IllegalStateException("watch_accounts_not_saved");
                return row;
            } catch (IllegalArgumentException | IllegalStateException failure) {
                throw failure;
            } catch (Exception unavailable) {
                // Do not attach an exception which could contain decrypted JSON or the JWT.
                throw new IllegalStateException("watch_accounts_unavailable");
            }
        }
    }

    /** Same stable server/account, including a renewed token; other accounts/servers remain untouched. */
    static boolean removeAccount(Context context, String server, String token) {
        synchronized (LOCK) {
            String normalized = ApiPolicy.server(server);
            String username = account(token);
            SharedPreferences prefs = prefs(context);
            SharedPreferences.Editor edit = prefs.edit();
            for (String id : ids(prefs)) {
                Record row = read(prefs, id);
                if (row != null && row.server.equals(normalized) && row.username.equals(username))
                    edit.remove(PREFIX + id);
            }
            return edit.commit();
        }
    }

    static boolean remove(Context context, String id) {
        synchronized (LOCK) {
            return validId(id) && prefs(context).edit().remove(PREFIX + id).commit();
        }
    }

    static boolean clear(Context context) {
        synchronized (LOCK) {
            if (!prefs(context).edit().clear().commit()) return false;
            try {
                KeyStore store = store();
                if (store.containsAlias(ALIAS)) store.deleteEntry(ALIAS);
                return true;
            } catch (Exception unavailable) { return false; }
        }
    }

    /** Admission check for callbacks: stable identity alone does not admit a stale JWT. */
    static boolean matches(Context context, Record expected) {
        synchronized (LOCK) {
            if (expected == null || !validId(expected.id)) return false;
            Record current = read(prefs(context), expected.id);
            return current != null && current.token.equals(expected.token);
        }
    }

    private static SharedPreferences prefs(Context context) {
        return context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    private static List<String> ids(SharedPreferences prefs) {
        List<String> ids = new ArrayList<>();
        for (String key : prefs.getAll().keySet()) {
            if (key.startsWith(PREFIX) && validId(key.substring(PREFIX.length())))
                ids.add(key.substring(PREFIX.length()));
        }
        Collections.sort(ids);
        return ids;
    }

    private static boolean validId(String value) {
        return value != null && value.matches("[0-9a-f]{64}");
    }

    private static String account(String token) {
        if (!ApiPolicy.jwt(token)) throw new IllegalArgumentException("invalid_auth_token");
        String username = AttachmentCache.username(token);
        if (username.isEmpty()) throw new IllegalArgumentException("watch_username_required");
        return username;
    }

    private static Record record(String server, String token, String session, String title, String baseline) {
        server = ApiPolicy.server(server);
        String username = account(token);
        session = AttachmentPolicy.session(session);
        title = title == null ? "" : title.trim().replace('\r', ' ').replace('\n', ' ');
        if (title.isEmpty()) title = BuildConfig.APP_NAME;
        if (title.length() > 40) title = title.substring(0, 40);
        baseline = baseline == null ? "" : baseline;
        if (baseline.length() > 2048 || baseline.matches("(?s).*[\\x00-\\x1f\\x7f].*"))
            throw new IllegalArgumentException("invalid_watch_baseline");
        // Identical to ReplyWatchService.scope without a service dependency.
        String id = AttachmentCache.key(server, token, "notification:" + session);
        return new Record(id, server, token, session, title, baseline, username);
    }

    private static Record read(SharedPreferences prefs, String id) {
        try {
            String encoded = prefs.getString(PREFIX + id, null);
            if (encoded == null || encoded.length() > MAX_ENVELOPE_CHARS) return null;
            JSONObject envelope = new JSONObject(encoded);
            if (envelope.length() != 3 || envelope.getInt("v") != 1) return null;
            String iv = envelope.getString("iv"), encrypted = envelope.getString("ciphertext");
            if (iv.length() > 128 || encrypted.length() > MAX_ENVELOPE_CHARS) return null;
            byte[] nonce = Base64.decode(iv, Base64.NO_WRAP);
            if (nonce.length != 12) return null;
            SecretKey key = key(false);
            if (key == null) return null;
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE, key, new GCMParameterSpec(128, nonce));
            cipher.updateAAD(aad(id));
            byte[] plain = cipher.doFinal(Base64.decode(encrypted, Base64.NO_WRAP));
            if (plain.length > MAX_PLAIN_BYTES) return null;
            JSONObject data = new JSONObject(new String(plain, StandardCharsets.UTF_8));
            if (data.length() != 7) return null;
            Record row = record(data.getString("server"), data.getString("token"), data.getString("session"),
                    data.getString("title"), data.getString("baseline"));
            return row.id.equals(id) && row.id.equals(data.getString("id"))
                    && row.username.equals(data.getString("username")) ? row : null;
        } catch (Exception unavailable) {
            // A corrupt row never clears its key, other rows, or the active-login vault.
            return null;
        }
    }

    private static byte[] aad(String id) {
        return (PREFS + "\n" + id).getBytes(StandardCharsets.UTF_8);
    }

    private static KeyStore store() throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
        return store;
    }

    private static SecretKey key(boolean create) throws Exception {
        KeyStore store = store();
        if (store.containsAlias(ALIAS)) return (SecretKey) store.getKey(ALIAS, null);
        if (!create) return null;
        KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
        generator.init(new KeyGenParameterSpec.Builder(ALIAS,
                KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setRandomizedEncryptionRequired(true).build());
        return generator.generateKey();
    }
}
