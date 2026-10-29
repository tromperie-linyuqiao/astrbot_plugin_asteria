package com.asteria.chat;

import android.content.Context;
import android.content.SharedPreferences;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import org.json.JSONObject;

/** Reuses the existing private attachment directory; token digests never grant server access. */
final class AttachmentCache {
    static final long TTL = 24L * 60 * 60 * 1000;
    static final long MAX_TOTAL = 64L * 1024 * 1024;
    static final int MAX_COUNT = 16;
    private static long generation;
    static synchronized long generation() { return generation; }
    static String key(String server, String token, String path) {
        String username = username(token);
        return digest(server + "\n" + (username.isEmpty() ? "token:" + digest(token) : "account:" + username) + "\n" + path);
    }
    // Presentation/cache partition only; this never verifies a JWT or grants API access.
    static String username(String token) {
        try {
            if (token == null || token.length() > 100000) return "";
            String[] parts = token.split("\\."); if (parts.length != 3) return "";
            JSONObject claims = new JSONObject(new String(android.util.Base64.decode(parts[1], android.util.Base64.URL_SAFE | android.util.Base64.NO_WRAP), StandardCharsets.UTF_8));
            Object value = claims.opt("username");
            if (!(value instanceof String)) return "";
            String name = (String) value;
            if (name.isEmpty() || name.length() > 128 || name.matches(".*[\\x00-\\x1f\\x7f].*")) return "";
            return name;
        } catch (Exception unavailable) { return ""; }
    }
    static String digest(String input) {
        try {
            byte[] bytes = MessageDigest.getInstance("SHA-256").digest(input.getBytes(StandardCharsets.UTF_8));
            StringBuilder text = new StringBuilder();
            for (byte value : bytes) text.append(String.format(java.util.Locale.ROOT, "%02x", value & 255));
            return text.toString();
        } catch (Exception impossible) { throw new IllegalStateException(impossible); }
    }
    private static SharedPreferences prefs(Context context) { return context.getSharedPreferences("asteria_chat_attachment_index", Context.MODE_PRIVATE); }
    static final class Entry {
        final File file; final String mime;
        Entry(File file, String mime) { this.file = file; this.mime = mime; }
    }
    static synchronized Entry find(Context context, String key) {
        try {
            JSONObject item = new JSONObject(prefs(context).getString(key, "{}"));
            File file = AttachmentPolicy.cacheFile(AttachmentFileProvider.directory(context), item.getString("file"));
            long age = System.currentTimeMillis() - item.getLong("saved_at");
            if (!file.isFile() || file.length() > AttachmentPolicy.MAX_BYTES || age < 0 || age > TTL) {
                prefs(context).edit().remove(key).apply(); return null;
            }
            file.setLastModified(System.currentTimeMillis());
            return new Entry(file, AttachmentPolicy.mime(item.getString("mime")));
        } catch (Exception missing) { return null; }
    }
    static synchronized Entry put(Context context, String key, byte[] bytes, String mime, long expectedGeneration) throws Exception {
        if (generation != expectedGeneration) throw new IllegalStateException("cache_cleared");
        if (bytes.length > AttachmentPolicy.MAX_BYTES) throw new IllegalArgumentException("download_too_large");
        File root = AttachmentFileProvider.directory(context);
        String name = java.util.UUID.randomUUID().toString().replace("-", "") + ".cache";
        File file = AttachmentPolicy.cacheFile(root, name), partial = new File(root, name + ".part");
        try {
            try (FileOutputStream out = new FileOutputStream(partial)) { out.write(bytes); out.getFD().sync(); }
            if (!partial.renameTo(file)) throw new java.io.IOException("cache_commit_failed");
            JSONObject item = new JSONObject().put("file", name).put("mime", mime).put("saved_at", System.currentTimeMillis());
            if (!prefs(context).edit().putString(key, item.toString()).commit()) throw new java.io.IOException("cache_index_failed");
            trim(context, root, file);
            return new Entry(file, mime);
        } catch (Exception failed) { file.delete(); throw failed; }
        finally { partial.delete(); }
    }
    private static void trim(Context context, File root, File keep) {
        File[] files = root.listFiles(file -> file.isFile() && AttachmentPolicy.cacheName(file.getName()));
        if (files == null) return;
        java.util.Arrays.sort(files, Comparator.comparingLong(File::lastModified));
        long total = 0; for (File file : files) total += file.length(); int count = files.length;
        for (File file : files) {
            if (file.equals(keep)) continue;
            if (count <= MAX_COUNT && total <= MAX_TOTAL && System.currentTimeMillis() - file.lastModified() <= TTL) continue;
            long length = file.length(); if (file.delete()) { new File(root, file.getName() + ".meta").delete(); count--; total -= length; }
        }
        SharedPreferences metadata = prefs(context); SharedPreferences.Editor edit = metadata.edit();
        for (String id : metadata.getAll().keySet()) {
            try {
                JSONObject row = new JSONObject(metadata.getString(id, "{}"));
                if (!AttachmentPolicy.cacheFile(root, row.getString("file")).isFile()
                        || System.currentTimeMillis() - row.getLong("saved_at") > TTL) edit.remove(id);
            } catch (Exception missing) { edit.remove(id); }
        }
        edit.apply();
    }
    static synchronized JSONObject clear(Context context) throws Exception {
        generation++;
        File root = AttachmentFileProvider.directory(context); int removed = 0, failed = 0; long bytes = 0;
        File[] files = root.listFiles();
        if (files != null) for (File file : files) {
            // Only our completed cache files/metadata; never touch a writer's .part or user files.
            if (!file.getName().matches("[0-9a-f]{32}\\.cache(?:\\.meta)?")
                    || !root.equals(file.getCanonicalFile().getParentFile())) continue;
            long size = file.length(); if (file.delete()) { if (AttachmentPolicy.cacheName(file.getName())) removed++; bytes += size; } else failed++;
        }
        if (!prefs(context).edit().clear().commit()) failed++;
        return new JSONObject().put("ok", failed == 0).put("removed", removed).put("bytes", bytes).put("failed", failed);
    }
    static synchronized JSONObject status(Context context) throws Exception {
        long bytes = 0; int count = 0;
        File[] files = AttachmentFileProvider.directory(context).listFiles();
        if (files != null) for (File file : files) if (AttachmentPolicy.cacheName(file.getName())) { bytes += file.length(); count++; }
        return new JSONObject().put("ok", true).put("bytes", bytes).put("count", count)
                .put("max_bytes", MAX_TOTAL).put("max_count", MAX_COUNT).put("ttl_hours", 24);
    }
}
