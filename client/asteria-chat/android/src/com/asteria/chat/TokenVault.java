package com.asteria.chat;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/** JWT only. Passwords are never persisted. Key material stays in AndroidKeyStore. */
final class TokenVault {
    private static final String ALIAS = "asteria_chat_auth_v1";
    // Activities and services each own a vault instance, but share one key and
    // encrypted record. Keep that entire record/key transaction process-wide.
    private static final Object LOCK = new Object();
    private final SharedPreferences prefs;

    TokenVault(Context context) {
        prefs = context.getSharedPreferences("asteria_chat_private", Context.MODE_PRIVATE);
    }

    String server() {
        synchronized (LOCK) {
            try { return ApiPolicy.server(prefs.getString("server", BuildConfig.DEFAULT_SERVER)); }
            catch (RuntimeException bad) { return BuildConfig.DEFAULT_SERVER; }
        }
    }

    void server(String value) {
        synchronized (LOCK) {
            if (!prefs.edit().putString("server", value).remove("ciphertext").remove("iv").commit())
                throw new IllegalStateException("settings_not_saved");
        }
    }

    String load(String server) {
        synchronized (LOCK) {
            // A callback carrying the prior server must not attempt to decrypt
            // (and then clear) the replacement server's valid credentials.
            if (!server().equals(server)) return null;
            try {
                String value = prefs.getString("ciphertext", null), iv = prefs.getString("iv", null);
                if (value == null || iv == null || value.length() > 100000 || iv.length() > 128) return null;
                Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
                cipher.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(128, Base64.decode(iv, Base64.NO_WRAP)));
                cipher.updateAAD(server.getBytes(StandardCharsets.UTF_8));
                String token = new String(cipher.doFinal(Base64.decode(value, Base64.NO_WRAP)), StandardCharsets.UTF_8);
                if (!ApiPolicy.jwt(token)) throw new IllegalStateException("invalid_saved_auth");
                return token;
            } catch (Exception unavailable) {
                clear();
                return null;
            }
        }
    }

    void save(String server, String token) throws Exception {
        synchronized (LOCK) {
            if (!ApiPolicy.jwt(token)) throw new IllegalArgumentException("invalid_auth_token");
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.ENCRYPT_MODE, key());
            cipher.updateAAD(server.getBytes(StandardCharsets.UTF_8));
            String value = Base64.encodeToString(cipher.doFinal(token.getBytes(StandardCharsets.UTF_8)), Base64.NO_WRAP);
            String iv = Base64.encodeToString(cipher.getIV(), Base64.NO_WRAP);
            if (!prefs.edit().putString("server", server).putString("ciphertext", value).putString("iv", iv).commit())
                throw new IllegalStateException("auth_not_saved");
        }
    }

    boolean clear() {
        synchronized (LOCK) {
            boolean saved = prefs.edit().remove("ciphertext").remove("iv").commit();
            try {
                KeyStore store = KeyStore.getInstance("AndroidKeyStore");
                store.load(null);
                if (store.containsAlias(ALIAS)) store.deleteEntry(ALIAS);
            } catch (Exception unavailable) { return false; }
            return saved;
        }
    }

    private SecretKey key() throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
        if (store.containsAlias(ALIAS)) return (SecretKey) store.getKey(ALIAS, null);
        KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
        generator.init(new KeyGenParameterSpec.Builder(ALIAS,
                KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setRandomizedEncryptionRequired(true).build());
        return generator.generateKey();
    }
}
