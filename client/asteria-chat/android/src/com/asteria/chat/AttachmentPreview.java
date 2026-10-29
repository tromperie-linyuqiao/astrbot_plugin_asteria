package com.asteria.chat;

import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.ColorSpace;
import android.graphics.Matrix;
import java.io.ByteArrayOutputStream;
import java.io.IOException;

/** Transient display thumbnail. The authenticated attachment cache always keeps the original bytes. */
final class AttachmentPreview {
    static final int MAX_SIDE = 768;
    static final int MAX_ENCODED = 512 * 1024;

    static int[] shape(int width, int height) {
        if (width <= 0 || height <= 0) throw new IllegalArgumentException("invalid_preview_dimensions");
        double scale = Math.min(1.0, (double) MAX_SIDE / Math.max(width, height));
        return new int[] { Math.max(1, (int) Math.round(width * scale)), Math.max(1, (int) Math.round(height * scale)) };
    }

    static Result create(byte[] source, String mime, AppearanceImageProcessor.CurrentCheck current) throws IOException {
        if (source == null || source.length == 0 || source.length > AttachmentPolicy.MAX_BYTES
                || !AttachmentPolicy.previewImage(mime) || !mime.equals(AttachmentPolicy.imageSignature(source)))
            throw new IOException("invalid_preview_source");
        Bitmap decoded = null, oriented = null, output = null;
        try {
            current.check();
            BitmapFactory.Options bounds = new BitmapFactory.Options(); bounds.inJustDecodeBounds = true;
            BitmapFactory.decodeByteArray(source, 0, source.length, bounds);
            int sample = AppearanceImagePolicy.sample(bounds.outWidth, bounds.outHeight);
            // In particular, already-small PNGs retain their exact pixels,
            // alpha and original bytes; small animated files also stay animated.
            if (Math.max(bounds.outWidth, bounds.outHeight) <= MAX_SIDE)
                return new Result(source, mime, bounds.outWidth, bounds.outHeight, false);
            BitmapFactory.Options options = new BitmapFactory.Options(); options.inSampleSize = sample;
            options.inPreferredConfig = Bitmap.Config.ARGB_8888;
            options.inPreferredColorSpace = ColorSpace.get(ColorSpace.Named.SRGB);
            decoded = BitmapFactory.decodeByteArray(source, 0, source.length, options);
            if (decoded == null || !AppearanceImagePolicy.decodedSafe(decoded.getWidth(), decoded.getHeight()))
                throw new IOException("preview_decode_limit");
            current.check();
            Matrix rotation = AppearanceImageProcessor.orientation(source, source.length);
            oriented = rotation.isIdentity() ? decoded : Bitmap.createBitmap(decoded, 0, 0, decoded.getWidth(), decoded.getHeight(), rotation, true);
            if (oriented != decoded) { decoded.recycle(); decoded = null; }
            int[] size = shape(oriented.getWidth(), oriented.getHeight());
            output = Bitmap.createScaledBitmap(oriented, size[0], size[1], true);
            if (output != oriented) { oriented.recycle(); oriented = null; }
            boolean alpha = output.hasAlpha(); String resultMime = alpha ? "image/png" : "image/jpeg";
            for (int round = 0; round < 5; round++) {
                current.check();
                ByteArrayOutputStream encoded = new ByteArrayOutputStream(64 * 1024);
                if (!output.compress(alpha ? Bitmap.CompressFormat.PNG : Bitmap.CompressFormat.JPEG, 82, encoded))
                    throw new IOException("preview_encode_failed");
                if (encoded.size() <= MAX_ENCODED)
                    return new Result(encoded.toByteArray(), resultMime, output.getWidth(), output.getHeight(), true);
                int width = Math.max(1, output.getWidth() * 3 / 4), height = Math.max(1, output.getHeight() * 3 / 4);
                Bitmap smaller = Bitmap.createScaledBitmap(output, width, height, true);
                if (smaller != output) output.recycle(); output = smaller;
            }
            throw new IOException("preview_encode_limit");
        } catch (OutOfMemoryError constrained) { throw new IOException("preview_memory_limit", constrained); }
        finally {
            if (output != null && !output.isRecycled()) output.recycle();
            if (oriented != null && !oriented.isRecycled()) oriented.recycle();
            if (decoded != null && !decoded.isRecycled()) decoded.recycle();
        }
    }

    static final class Result {
        final byte[] bytes; final String mime; final int width, height; final boolean thumbnail;
        Result(byte[] bytes, String mime, int width, int height, boolean thumbnail) {
            this.bytes = bytes; this.mime = mime; this.width = width; this.height = height; this.thumbnail = thumbnail;
        }
    }
}
