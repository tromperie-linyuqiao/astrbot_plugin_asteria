package com.asteria.chat;

import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.ColorSpace;
import android.graphics.Matrix;
import android.graphics.Paint;
import android.graphics.Rect;
import android.media.ExifInterface;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.OutputStream;

/** Local-only bounded image decode; JPEG output strips source metadata and takes a static frame. */
final class AppearanceImageProcessor {
    interface CurrentCheck { void check(); }
    private AppearanceImageProcessor() { }

    static Result process(byte[] source, int length, String kind, CurrentCheck current) throws IOException {
        AppearanceImagePolicy.kind(kind);
        if (source == null || length <= 0 || length > source.length || length > AppearanceImagePolicy.MAX_INPUT_BYTES)
            throw new IOException("appearance_input_too_large_or_empty");
        if (AttachmentPolicy.imageSignature(java.util.Arrays.copyOf(source, Math.min(length, 12))).isEmpty())
            throw new IOException("unsupported_image_format");
        Bitmap decoded = null, oriented = null, output = null;
        try {
            current.check();
            BitmapFactory.Options bounds = new BitmapFactory.Options();
            bounds.inJustDecodeBounds = true;
            BitmapFactory.decodeByteArray(source, 0, length, bounds);
            if (bounds.outWidth <= 0 || bounds.outHeight <= 0 || !AttachmentPolicy.previewImage(bounds.outMimeType == null ? "" : bounds.outMimeType))
                throw new IOException("unsupported_or_invalid_image");
            BitmapFactory.Options options = new BitmapFactory.Options();
            options.inSampleSize = AppearanceImagePolicy.sample(bounds.outWidth, bounds.outHeight);
            options.inPreferredConfig = Bitmap.Config.ARGB_8888;
            options.inPreferredColorSpace = ColorSpace.get(ColorSpace.Named.SRGB);
            current.check();
            decoded = BitmapFactory.decodeByteArray(source, 0, length, options);
            if (decoded == null || !AppearanceImagePolicy.decodedSafe(decoded.getWidth(), decoded.getHeight()))
                throw new IOException("sampled_image_invalid_or_oversized");
            current.check();
            Matrix orientation = orientation(source, length);
            oriented = orientation.isIdentity() ? decoded : Bitmap.createBitmap(decoded, 0, 0,
                    decoded.getWidth(), decoded.getHeight(), orientation, true);
            if (oriented != decoded) { decoded.recycle(); decoded = null; }
            int width = oriented.getWidth(), height = oriented.getHeight();
            int[] shape = AppearanceImagePolicy.output(kind, width, height);
            output = Bitmap.createBitmap(shape[0], shape[1], Bitmap.Config.ARGB_8888);
            Canvas canvas = new Canvas(output);
            canvas.drawColor(Color.WHITE);
            int side = Math.min(width, height);
            Rect sourceRect = kind.equals("avatar")
                    ? new Rect((width - side) / 2, (height - side) / 2, (width - side) / 2 + side, (height - side) / 2 + side)
                    : new Rect(0, 0, width, height);
            canvas.drawBitmap(oriented, sourceRect, new Rect(0, 0, shape[0], shape[1]),
                    new Paint(Paint.ANTI_ALIAS_FLAG | Paint.FILTER_BITMAP_FLAG | Paint.DITHER_FLAG));
            for (int round = 0; round < 5; round++) {
                for (int quality : new int[] {88, 76, 64, 52, 40}) {
                    current.check();
                    byte[] jpeg = encode(output, quality);
                    if (jpeg != null) return new Result(jpeg, output.getWidth(), output.getHeight(), kind);
                }
                if (kind.equals("avatar")) break; // Avatar stays exactly 256 square; never silently changes its contract.
                int nextWidth = Math.max(1, output.getWidth() * 3 / 4), nextHeight = Math.max(1, output.getHeight() * 3 / 4);
                if (nextWidth == output.getWidth() && nextHeight == output.getHeight()) break;
                current.check();
                Bitmap smaller = Bitmap.createScaledBitmap(output, nextWidth, nextHeight, true);
                if (smaller != output) output.recycle();
                output = smaller;
            }
            throw new IOException("appearance_output_exceeds_limit");
        } catch (OutOfMemoryError constrainedDevice) {
            throw new IOException("appearance_memory_limit", constrainedDevice);
        } finally {
            if (output != null && !output.isRecycled()) output.recycle();
            if (oriented != null && !oriented.isRecycled()) oriented.recycle();
            if (decoded != null && !decoded.isRecycled()) decoded.recycle();
        }
    }

    private static byte[] encode(Bitmap bitmap, int quality) {
        LimitedOutput output = new LimitedOutput();
        try {
            if (!bitmap.compress(Bitmap.CompressFormat.JPEG, quality, output) || output.exceeded || output.bytes.size() == 0) return null;
            return output.bytes.toByteArray();
        } catch (OutputLimit exceeded) { return null; }
    }

    private static Matrix orientation(byte[] source, int length) {
        Matrix matrix = new Matrix();
        try {
            ExifInterface exif = new ExifInterface(new ByteArrayInputStream(source, 0, length));
            int orientation = exif.getAttributeInt(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL);
            switch (orientation) {
                case ExifInterface.ORIENTATION_FLIP_HORIZONTAL: matrix.setScale(-1, 1); break;
                case ExifInterface.ORIENTATION_ROTATE_180: matrix.setRotate(180); break;
                case ExifInterface.ORIENTATION_FLIP_VERTICAL: matrix.setScale(1, -1); break;
                case ExifInterface.ORIENTATION_TRANSPOSE: matrix.setRotate(90); matrix.postScale(-1, 1); break;
                case ExifInterface.ORIENTATION_ROTATE_90: matrix.setRotate(90); break;
                case ExifInterface.ORIENTATION_TRANSVERSE: matrix.setRotate(-90); matrix.postScale(-1, 1); break;
                case ExifInterface.ORIENTATION_ROTATE_270: matrix.setRotate(-90); break;
                default: break;
            }
        } catch (IOException notExif) { /* PNG/GIF and unsupported EXIF still decode normally. */ }
        return matrix;
    }

    private static final class OutputLimit extends RuntimeException { }
    private static final class LimitedOutput extends OutputStream {
        final ByteArrayOutputStream bytes = new ByteArrayOutputStream(64 * 1024);
        boolean exceeded;
        @Override public void write(int value) {
            if (bytes.size() >= AppearanceImagePolicy.MAX_OUTPUT_BYTES) { exceeded = true; throw new OutputLimit(); }
            bytes.write(value);
        }
        @Override public void write(byte[] value, int offset, int length) {
            if (length < 0 || bytes.size() + (long) length > AppearanceImagePolicy.MAX_OUTPUT_BYTES) {
                exceeded = true; throw new OutputLimit();
            }
            bytes.write(value, offset, length);
        }
    }

    static final class Result {
        final byte[] jpeg;
        final int width, height;
        final String kind;
        Result(byte[] jpeg, int width, int height, String kind) {
            this.jpeg = jpeg; this.width = width; this.height = height; this.kind = kind;
        }
    }
}
