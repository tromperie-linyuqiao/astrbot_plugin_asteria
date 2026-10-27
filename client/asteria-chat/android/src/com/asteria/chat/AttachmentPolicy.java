package com.asteria.chat;

import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.Locale;
import java.io.File;
import java.io.IOException;

/** Attachment syntax/size checks; ownership remains the server's responsibility. */
public final class AttachmentPolicy {
    public static final int MAX_BYTES = 8 * 1024 * 1024;
    private AttachmentPolicy() { }

    public static String session(String value) {
        if (value == null || value.isEmpty() || value.length() > 512 || controls(value))
            throw new IllegalArgumentException("invalid_session_id");
        return value;
    }

    public static String filename(String value) {
        if (value == null || value.isEmpty() || value.length() > 255 || controls(value)
                || value.equals(".") || value.equals("..") || value.indexOf('/') >= 0
                || value.indexOf('\\') >= 0 || value.indexOf(':') >= 0 || value.indexOf('%') >= 0)
            throw new IllegalArgumentException("invalid_attachment_filename");
        return value;
    }

    public static String displayName(String value) {
        if (value == null || value.trim().isEmpty()) return "attachment.bin";
        StringBuilder result = new StringBuilder();
        for (int i = 0; i < value.length() && result.length() < 180; i++) {
            char c = value.charAt(i);
            result.append(c < 0x20 || c == 0x7f || c == '"' || c == '\\' || c == '/' || c == ':' ? '_' : c);
        }
        return result.toString();
    }

    public static String mime(String value) {
        String candidate = value == null ? "" : value.split(";", 2)[0].trim().toLowerCase(Locale.ROOT);
        return candidate.matches("[a-z0-9][a-z0-9!#$&^_.+-]{0,79}/[a-z0-9][a-z0-9!#$&^_.+-]{0,79}")
                ? candidate : "application/octet-stream";
    }

    public static boolean previewImage(String value) {
        return value.equals("image/png") || value.equals("image/jpeg")
                || value.equals("image/gif") || value.equals("image/webp");
    }

    public static String imageSignature(byte[] value) {
        if (value.length >= 8 && (value[0] & 255) == 137 && value[1] == 80 && value[2] == 78 && value[3] == 71
                && value[4] == 13 && value[5] == 10 && value[6] == 26 && value[7] == 10) return "image/png";
        if (value.length >= 3 && (value[0] & 255) == 255 && (value[1] & 255) == 216 && (value[2] & 255) == 255)
            return "image/jpeg";
        if (value.length >= 6 && value[0] == 71 && value[1] == 73 && value[2] == 70 && value[3] == 56
                && (value[4] == 55 || value[4] == 57) && value[5] == 97) return "image/gif";
        if (value.length >= 12 && value[0] == 82 && value[1] == 73 && value[2] == 70 && value[3] == 70
                && value[8] == 87 && value[9] == 69 && value[10] == 66 && value[11] == 80) return "image/webp";
        return "";
    }

    public static String downloadPath(String sessionId, String filename) {
        try {
            return "/chat/file?session_id=" + URLEncoder.encode(session(sessionId), StandardCharsets.UTF_8.name())
                    + "&filename=" + URLEncoder.encode(filename(filename), StandardCharsets.UTF_8.name());
        } catch (java.io.UnsupportedEncodingException impossible) { throw new AssertionError(impossible); }
    }

    public static boolean cacheName(String value) { return value != null && value.matches("[0-9a-f]{32}\\.cache"); }

    public static File cacheFile(File directory, String name) throws IOException {
        if (!cacheName(name)) throw new IOException("invalid_cache_key");
        File root = directory.getCanonicalFile(), file = new File(root, name).getCanonicalFile();
        if (!root.equals(file.getParentFile())) throw new IOException("cache_path_escape");
        return file;
    }

    private static boolean controls(String value) {
        for (int i = 0; i < value.length(); i++)
            if (value.charAt(i) < 0x20 || value.charAt(i) == 0x7f) return true;
        return false;
    }
}
