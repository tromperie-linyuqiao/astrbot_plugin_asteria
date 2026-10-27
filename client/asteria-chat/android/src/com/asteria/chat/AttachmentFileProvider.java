package com.asteria.chat;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.content.Context;
import android.content.pm.ProviderInfo;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileNotFoundException;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.Comparator;
import org.json.JSONObject;

/** Zero-dependency FileProvider for this app's downloaded cache, with read-only URI grants. */
public final class AttachmentFileProvider extends ContentProvider {
    private static final String AUTHORITY = "com.asteria.chat.files";

    @Override public void attachInfo(Context context, ProviderInfo info) {
        if (info.exported || !info.grantUriPermissions || !AUTHORITY.equals(info.authority))
            throw new SecurityException("Attachment provider must be private with explicit URI grants");
        super.attachInfo(context, info);
    }

    @Override public boolean onCreate() { return true; }

    static File directory(Context context) throws java.io.IOException {
        File root = new File(context.getCacheDir(), "chat_attachments");
        if (!root.isDirectory() && !root.mkdirs()) throw new java.io.IOException("cache_unavailable");
        return root.getCanonicalFile();
    }

    static Uri publish(Context context, File file, String displayName, String mime) throws Exception {
        File root = directory(context);
        File actual = file.getCanonicalFile();
        if (!root.equals(actual.getParentFile()) || !opaque(actual.getName()) || !actual.isFile())
            throw new java.io.IOException("invalid_cache_file");
        JSONObject metadata = new JSONObject();
        metadata.put("display_name", AttachmentPolicy.displayName(displayName));
        metadata.put("mime_type", AttachmentPolicy.mime(mime));
        try (FileOutputStream output = new FileOutputStream(new File(root, actual.getName() + ".meta"))) {
            output.write(metadata.toString().getBytes(StandardCharsets.UTF_8));
        }
        trimCache(root, actual);
        return new Uri.Builder().scheme("content").authority(AUTHORITY)
                .appendPath("attachments").appendPath(actual.getName()).build();
    }

    private File resolve(Uri uri) throws FileNotFoundException {
        try {
            if (!"content".equals(uri.getScheme()) || !AUTHORITY.equals(uri.getAuthority())
                    || uri.getQuery() != null || uri.getFragment() != null || uri.getPathSegments().size() != 2
                    || !"attachments".equals(uri.getPathSegments().get(0))) throw new FileNotFoundException();
            String name = uri.getPathSegments().get(1);
            if (!opaque(name)) throw new FileNotFoundException();
            File root = directory(getContext()), file = AttachmentPolicy.cacheFile(root, name);
            if (!root.equals(file.getParentFile()) || !file.isFile()) throw new FileNotFoundException();
            return file;
        } catch (Exception rejected) { throw new FileNotFoundException("Unknown attachment"); }
    }

    private static boolean opaque(String value) { return AttachmentPolicy.cacheName(value); }

    private JSONObject metadata(File file) {
        try (FileInputStream input = new FileInputStream(new File(file.getParentFile(), file.getName() + ".meta"))) {
            byte[] bytes = new byte[2049];
            int length = input.read(bytes);
            if (length < 0 || length > 2048) return new JSONObject();
            return new JSONObject(new String(bytes, 0, length, StandardCharsets.UTF_8));
        } catch (Exception missing) { return new JSONObject(); }
    }

    @Override public String getType(Uri uri) {
        try { return AttachmentPolicy.mime(metadata(resolve(uri)).optString("mime_type", "")); }
        catch (FileNotFoundException missing) { return "application/octet-stream"; }
    }

    @Override public Cursor query(Uri uri, String[] projection, String selection, String[] args, String sort) {
        try {
            File file = resolve(uri);
            JSONObject meta = metadata(file);
            String[] columns = projection == null ? new String[] { OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE } : projection;
            MatrixCursor result = new MatrixCursor(columns, 1);
            Object[] row = new Object[columns.length];
            for (int i = 0; i < columns.length; i++) {
                if (OpenableColumns.DISPLAY_NAME.equals(columns[i])) row[i] = meta.optString("display_name", "attachment");
                else if (OpenableColumns.SIZE.equals(columns[i])) row[i] = file.length();
            }
            result.addRow(row);
            return result;
        } catch (FileNotFoundException missing) { return null; }
    }

    @Override public ParcelFileDescriptor openFile(Uri uri, String mode) throws FileNotFoundException {
        if (!"r".equals(mode)) throw new FileNotFoundException("Read-only attachment");
        return ParcelFileDescriptor.open(resolve(uri), ParcelFileDescriptor.MODE_READ_ONLY);
    }

    @Override public Uri insert(Uri uri, ContentValues values) { throw new UnsupportedOperationException("Read only"); }
    @Override public int update(Uri uri, ContentValues values, String where, String[] args) { throw new UnsupportedOperationException("Read only"); }
    @Override public int delete(Uri uri, String where, String[] args) { throw new UnsupportedOperationException("Read only"); }

    private static void trimCache(File root, File current) {
        File[] files = root.listFiles(file -> file.isFile() && opaque(file.getName()));
        if (files == null) return;
        Arrays.sort(files, Comparator.comparingLong(File::lastModified));
        long total = 0;
        for (File file : files) total += file.length();
        int count = files.length;
        for (File file : files) {
            if (file.equals(current)) continue;
            if (count <= 16 && total <= 64L * 1024 * 1024
                    && System.currentTimeMillis() - file.lastModified() <= 24L * 60 * 60 * 1000) continue;
            long length = file.length();
            if (file.delete()) {
                new File(root, file.getName() + ".meta").delete();
                total -= length;
                count--;
            }
        }
    }
}
