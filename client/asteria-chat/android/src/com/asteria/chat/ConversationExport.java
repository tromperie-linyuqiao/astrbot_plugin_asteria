package com.asteria.chat;

import java.io.IOException;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;

/** Bounded local document bytes; the SAF caller owns and closes its selected stream. */
public final class ConversationExport {
    public static final int MAX_BYTES = 2 * 1024 * 1024;
    private ConversationExport() { }

    public interface Guard { void check() throws IOException; }
    public static final class Document {
        public final String filename;
        private final byte[] bytes;
        private Document(String filename, byte[] bytes) { this.filename = filename; this.bytes = bytes; }
        public int size() { return bytes.length; }
    }

    public static Document prepare(String filename, String markdown) {
        if (filename == null || filename.length() > 120
                || !filename.matches("[A-Za-z0-9][A-Za-z0-9._ -]*\\.md") || filename.contains(".."))
            throw new IllegalArgumentException("invalid_export_filename");
        if (markdown == null || markdown.length() > MAX_BYTES) throw new IllegalArgumentException("export_too_large");
        int count = 0;
        for (int i = 0; i < markdown.length(); i++) {
            char c = markdown.charAt(i);
            if (c < 0x80) count++;
            else if (c < 0x800) count += 2;
            else if (Character.isHighSurrogate(c)) {
                if (i + 1 >= markdown.length() || !Character.isLowSurrogate(markdown.charAt(++i)))
                    throw new IllegalArgumentException("invalid_export_unicode");
                count += 4;
            } else if (Character.isLowSurrogate(c)) throw new IllegalArgumentException("invalid_export_unicode");
            else count += 3;
            if (count > MAX_BYTES) throw new IllegalArgumentException("export_too_large");
        }
        return new Document(filename, markdown.getBytes(StandardCharsets.UTF_8));
    }

    public static long write(Document document, OutputStream output, Guard guard) throws IOException {
        if (document == null || output == null || guard == null) throw new IllegalArgumentException("export_stream_required");
        for (int offset = 0; offset < document.bytes.length;) {
            guard.check();
            int length = Math.min(8192, document.bytes.length - offset);
            output.write(document.bytes, offset, length);
            offset += length;
        }
        guard.check();
        output.flush();
        guard.check();
        return document.bytes.length;
    }
}
