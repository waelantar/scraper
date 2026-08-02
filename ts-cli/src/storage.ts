// ts-cli/src/storage.ts
import {
    appendFileSync,
    readFileSync,
    existsSync,
    openSync,
    closeSync,
    unlinkSync,
    ftruncateSync,
    statSync,
} from 'fs';
import { createHash } from 'crypto';
import type { Entry } from './types.js';

/**
 * A single-writer, append-only JSONL store with per-line checksums.
 *
 * - Lock file: <filePath>.lock, acquired with `wx` flag.
 * - On load: verifies checksums; stops at first corruption and truncates the file.
 * - Checksum excludes the `checksum` field itself.
 * - Stale lock recovery: if lock file is older than `staleLockMs`, it is removed.
 */
export class JsonlStorage {
    private lastEntryId: string | null = null;
    private locked = false;
    private lockPath: string;

    constructor(
        private filePath: string,
        private staleLockMs: number = 30000, // default 30s
    ) {
        this.lockPath = filePath + '.lock';
    }

    /** Acquire the lock; throws if already locked by another process. */
    lock(): void {
        if (this.locked) return;

        // Check for stale lock
        if (existsSync(this.lockPath)) {
            const stats = statSync(this.lockPath);
            const age = Date.now() - stats.mtimeMs;
            if (age > this.staleLockMs) {
                // Remove stale lock
                try {
                    unlinkSync(this.lockPath);
                } catch (_) {
                    // Ignore if it's gone
                }
            }
        }

        try {
            const fd = openSync(this.lockPath, 'wx');
            closeSync(fd);
            this.locked = true;
        } catch (err) {
            throw new Error(`Lock file exists: ${this.lockPath}`);
        }
    }

    /** Release the lock. */
    unlock(): void {
        if (!this.locked) return;
        try {
            unlinkSync(this.lockPath);
            this.locked = false;
        } catch (_) {
            this.locked = false;
        }
    }

    /**
     * Append an entry to the file.
     * - Computes the checksum (excluding the `checksum` field).
     * - Acquires the lock.
     * - Appends a JSON line + newline.
     * - Updates `lastEntryId`.
     * - Releases the lock.
     * - Returns the entry ID.
     */
    append(entry: Entry): string {
        const { checksum: _, ...payload } = entry;
        const computed = createHash('sha256')
            .update(JSON.stringify(payload))
            .digest('hex');

        const entryWithChecksum = { ...entry, checksum: computed };
        const line = JSON.stringify(entryWithChecksum) + '\n';

        this.lock();
        try {
            appendFileSync(this.filePath, line, 'utf-8');
            this.lastEntryId = entry.id;
        } finally {
            this.unlock();
        }
        return entry.id;
    }

    /**
     * Load all valid entries from the file.
     * - Stops at the first corrupt line (checksum mismatch or malformed JSON).
     * - Truncates the file at that point (removes the corrupt tail).
     * - Returns a Map<id, Entry> of all successfully loaded entries.
     */
    load(): Map<string, Entry> {
        const map = new Map<string, Entry>();
        this.lastEntryId = null;

        if (!existsSync(this.filePath)) {
            return map;
        }

        const buffer = readFileSync(this.filePath);
        const lines: string[] = [];
        const lineOffsets: number[] = [];
        let start = 0;
        let hasTrailingNewline = false;

        // Split buffer by newline, but preserve byte offsets
        for (let i = 0; i < buffer.length; i++) {
            if (buffer[i] === 10) { // newline
                const line = buffer.subarray(start, i).toString('utf-8');
                lines.push(line);
                lineOffsets.push(start);
                start = i + 1;
                hasTrailingNewline = true;
            }
        }

        // Check for partial line at the end
        if (start < buffer.length) {
            // There is data after the last newline -> partial line -> corruption
            const partialLine = buffer.subarray(start).toString('utf-8');
            if (partialLine.trim()) {
                // We have a partial line; truncate at the last newline
                const fd = openSync(this.filePath, 'r+');
                try {
                    const lastNewlinePos = buffer.lastIndexOf(10);
                    if (lastNewlinePos >= 0) {
                        ftruncateSync(fd, lastNewlinePos + 1);
                    } else {
                        // No newline at all -> empty file
                        ftruncateSync(fd, 0);
                    }
                } finally {
                    closeSync(fd);
                }
                // Re-read truncated file or just return empty map because truncation removed all?
                // Actually we should re-load after truncation, but we can just return the current map.
                // But we must also update lastEntryId. We'll re-load recursively once.
                return this.load(); // Recurse to load the truncated file
            }
        }

        // Process lines
        for (let i = 0; i < lines.length; i++) {
            const line = lines[i];
            if (!line.trim()) continue;

            let parsed: Entry;
            try {
                parsed = JSON.parse(line);
            } catch (_) {
                // Malformed JSON -> corruption
                console.warn(`Malformed JSON at line ${i + 1}; truncating after ${map.size} entries.`);
                const fd = openSync(this.filePath, 'r+');
                try {
                    ftruncateSync(fd, lineOffsets[i]);
                } finally {
                    closeSync(fd);
                }
                break;
            }

            const { checksum: storedChecksum, ...payload } = parsed;
            const computed = createHash('sha256')
                .update(JSON.stringify(payload))
                .digest('hex');

            if (storedChecksum !== computed) {
                console.warn(`Checksum mismatch at line ${i + 1}; truncating after ${map.size} entries.`);
                const fd = openSync(this.filePath, 'r+');
                try {
                    ftruncateSync(fd, lineOffsets[i]);
                } finally {
                    closeSync(fd);
                }
                break;
            }

            map.set(parsed.id, parsed);
            this.lastEntryId = parsed.id;
        }

        return map;
    }

    /** Returns the ID of the last successfully appended entry, or null if none. */
    getLastEntryId(): string | null {
        return this.lastEntryId;
    }
}