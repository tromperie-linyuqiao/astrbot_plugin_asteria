package com.asteria.chat;

/** Pure geometry and admission limits; Android codecs are kept in AppearanceImageProcessor. */
public final class AppearanceImagePolicy {
    public static final int MAX_INPUT_BYTES = 8 * 1024 * 1024;
    public static final int MAX_OUTPUT_BYTES = 512 * 1024;
    public static final long MAX_DECODE_PIXELS = 4L * 1024 * 1024;
    public static final long MAX_SOURCE_PIXELS = 64000000L;
    public static final int MAX_SOURCE_SIDE = 16384;
    private AppearanceImagePolicy() { }

    public static String kind(String value) {
        if (!"avatar".equals(value) && !"background".equals(value))
            throw new IllegalArgumentException("invalid_appearance_kind");
        return value;
    }

    public static int sample(int width, int height) {
        dimensions(width, height);
        if (width > MAX_SOURCE_SIDE || height > MAX_SOURCE_SIDE || (long) width * height > MAX_SOURCE_PIXELS)
            throw new IllegalArgumentException("source_image_dimensions_exceed_limit");
        int sample = 1;
        while (ceil(width, sample) * ceil(height, sample) > MAX_DECODE_PIXELS
                || Math.max(ceil(width, sample), ceil(height, sample)) > 2048) {
            if (sample >= 1 << 29) throw new IllegalArgumentException("image_dimensions_too_large");
            sample *= 2;
        }
        return sample;
    }

    public static int[] output(String kind, int width, int height) {
        kind(kind);
        dimensions(width, height);
        if (kind.equals("avatar")) return new int[] {256, 256};
        double scale = Math.min(1.0, 1280.0 / Math.max(width, height));
        return new int[] {Math.max(1, (int) Math.round(width * scale)), Math.max(1, (int) Math.round(height * scale))};
    }

    public static boolean decodedSafe(int width, int height) {
        return width > 0 && height > 0 && (long) width * height <= MAX_DECODE_PIXELS
                && Math.max(width, height) <= 2048;
    }

    private static long ceil(int value, int divisor) { return ((long) value + divisor - 1) / divisor; }
    private static void dimensions(int width, int height) {
        if (width <= 0 || height <= 0) throw new IllegalArgumentException("invalid_image_dimensions");
    }
}
