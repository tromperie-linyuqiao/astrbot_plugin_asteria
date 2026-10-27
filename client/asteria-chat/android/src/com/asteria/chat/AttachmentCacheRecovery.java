package com.asteria.chat;

import java.io.File;
import java.io.IOException;

/** One process-local startup pass. Once any writer is admitted this guard never cleans again. */
final class AttachmentCacheRecovery {
    private boolean checked;
    private boolean writerAdmitted;

    synchronized void admitWriter() { writerAdmitted = true; }

    synchronized Result recoverBeforeWriters(File directory) throws IOException {
        if (writerAdmitted) return new Result("skipped_writer_admitted", 0, 0);
        if (checked) return new Result("already_checked", 0, 0);
        checked = true;
        File root = directory.getCanonicalFile();
        File[] entries = root.listFiles();
        if (entries == null) return new Result("directory_unavailable", 0, 0);
        int deleted = 0, failed = 0;
        for (File file : entries) {
            if (!file.getName().matches("[0-9a-f]{32}\\.cache\\.part")) continue;
            try {
                File canonical = file.getCanonicalFile();
                if (!file.isFile() || !root.equals(canonical.getParentFile())
                        || !file.getName().equals(canonical.getName())) { failed++; continue; }
                if (file.delete()) deleted++; else failed++;
            } catch (IOException inaccessible) { failed++; }
        }
        return new Result(failed == 0 ? "completed" : "partial", deleted, failed);
    }

    static final class Result {
        final String status;
        final int removed, failed;
        Result(String status, int removed, int failed) { this.status = status; this.removed = removed; this.failed = failed; }
    }
}
