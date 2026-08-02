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
import type { Entry, LeafEntry } from './types.js';

export class JsonlStorage {
    private lastEntryId: string | null = null;
    private lastLeafId: string | null = null;
    private locked = false;
    private lockPath: string;

    constructor(
        private filePath: string,
        private staleLockMs: number = 30000,
    ) {
        this.lockPath = filePath + '.lock';
    }

    lock(): void {
        if (this.locked) return;

        if (existsSync(this.lockPath)) {
            const stats = statSync(this.lockPath);
            const age = Date.now() - stats.mtimeMs;
            if (age > this.staleLockMs) {
                try {
                    unlinkSync(this.lockPath);
                } catch (_) {}
            }
        }

        try {
            const fd = openSync(this.lockPath, 'wx');
            closeSync(fd);
            this.locked = true;
        } catch (_) {
            throw new Error(`Lock file exists: ${this.lockPath}`);
        }
    }

    unlock(): void {
        if (!this.locked) return;
        try {
            unlinkSync(this.lockPath);
            this.locked = false;
        } catch (_) {
            this.locked = false;
        }
    }

    append(entry: Entry): Entry {
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
        return entryWithChecksum;
    }

    load(): Map<string, Entry> {
        const map = new Map<string, Entry>();
        this.lastEntryId = null;
        this.lastLeafId = null;

        if (!existsSync(this.filePath)) {
            return map;
        }

        const buffer = readFileSync(this.filePath);
        const lines: string[] = [];
        const lineOffsets: number[] = [];
        let start = 0;

        for (let i = 0; i < buffer.length; i++) {
            if (buffer[i] === 10) {
                const line = buffer.subarray(start, i).toString('utf-8');
                lines.push(line);
                lineOffsets.push(start);
                start = i + 1;
            }
        }

        if (start < buffer.length) {
            const partialLine = buffer.subarray(start).toString('utf-8');
            if (partialLine.trim()) {
                const fd = openSync(this.filePath, 'r+');
                try {
                    const lastNewlinePos = buffer.lastIndexOf(10);
                    if (lastNewlinePos >= 0) {
                        ftruncateSync(fd, lastNewlinePos + 1);
                    } else {
                        ftruncateSync(fd, 0);
                    }
                } finally {
                    closeSync(fd);
                }
                return this.load();
            }
        }

        for (let i = 0; i < lines.length; i++) {
            const line = lines[i];
            if (!line.trim()) continue;

            let parsed: Entry;
            try {
                parsed = JSON.parse(line);
            } catch (_) {
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

            if (parsed.type === 'leaf') {
                this.lastLeafId = (parsed as LeafEntry).targetId;
            }
        }

        return map;
    }

    getLastEntryId(): string | null {
        return this.lastEntryId;
    }

    getLeafId(): string | null {
        return this.lastLeafId;
    }
}