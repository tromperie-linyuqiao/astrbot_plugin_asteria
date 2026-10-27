package com.asteria.chat;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;

/** Bounded streaming multipart body. Does not open connections or retry a transfer. */
public final class AttachmentStreams {
    public interface CurrentCheck { void check(); }
    private AttachmentStreams() { }

    public static long multipart(OutputStream output, InputStream source, String boundary, String session,
            String name, String mime, CurrentCheck current) throws IOException {
        if (boundary == null || !boundary.matches("[A-Za-z0-9]{1,80}")) throw new IllegalArgumentException("invalid_boundary");
        current.check();
        write(output, "--" + boundary + "\r\nContent-Disposition: form-data; name=\"session_id\"\r\n\r\n"
                + AttachmentPolicy.session(session) + "\r\n--" + boundary
                + "\r\nContent-Disposition: form-data; name=\"file\"; filename=\"" + AttachmentPolicy.displayName(name)
                + "\"\r\nContent-Type: " + AttachmentPolicy.mime(mime) + "\r\n\r\n");
        long bytes = copy(source, output, current);
        current.check();
        write(output, "\r\n--" + boundary + "--\r\n");
        return bytes;
    }

    public static long copy(InputStream source, OutputStream output, CurrentCheck current) throws IOException {
        byte[] buffer = new byte[64 * 1024];
        int length;
        long total = 0;
        while ((length = source.read(buffer)) != -1) {
            current.check();
            if (length == 0) throw new IOException("attachment_stream_made_no_progress");
            if (Thread.currentThread().isInterrupted() || total + length > AttachmentPolicy.MAX_BYTES)
                throw new IOException("attachment_cancelled_or_too_large");
            output.write(buffer, 0, length);
            total += length;
        }
        return total;
    }

    private static void write(OutputStream stream, String value) throws IOException {
        stream.write(value.getBytes(StandardCharsets.UTF_8));
    }
}
