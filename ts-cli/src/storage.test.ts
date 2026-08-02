import { describe, it, before, after } from 'node:test';
import assert from 'node:assert';
import { mkdtemp, rm, readFile, writeFile } from 'node:fs/promises';
import { existsSync } from 'fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { JsonlStorage } from './storage.js';
import type { MessageEntry, Entry } from './types.js';

function makeMessage(id: string, parentId: string | null, content: string): MessageEntry {
    return {
        id,
        parentId,
        type: 'message',
        timestamp: Date.now(),
        checksum: '',
        role: 'user',
        content,
    };
}

function asMessageEntry(e: Entry): MessageEntry {
    assert.strictEqual(e.type, 'message');
    return e as MessageEntry;
}

describe('JsonlStorage', () => {
    let tempDir: string;

    before(async () => {
        tempDir = await mkdtemp(join(tmpdir(), 'storage-test-'));
    });

    after(async () => {
        await rm(tempDir, { recursive: true, force: true });
    });

    it('appends and loads entries', () => {
        const path = join(tempDir, 'session.jsonl');
        const storage = new JsonlStorage(path);

        const entries = [
            makeMessage('msg1', null, 'Hello'),
            makeMessage('msg2', 'msg1', 'World'),
            makeMessage('msg3', 'msg2', '!'),
        ];

        for (const e of entries) {
            const id = storage.append(e);
            assert.strictEqual(id, e.id);
        }

        const map = storage.load();
        assert.strictEqual(map.size, 3);
        for (const e of entries) {
            const loaded = map.get(e.id);
            assert.ok(loaded);
            const msg = asMessageEntry(loaded);
            assert.strictEqual(msg.id, e.id);
            assert.strictEqual(msg.parentId, e.parentId);
            assert.strictEqual(msg.content, e.content);
            assert.ok(msg.checksum.length > 0);
        }
        assert.strictEqual(storage.getLastEntryId(), 'msg3');
    });

    it('handles empty file', async () => {
        const path = join(tempDir, 'empty.jsonl');
        await writeFile(path, '');
        const storage = new JsonlStorage(path);
        const map = storage.load();
        assert.strictEqual(map.size, 0);
        assert.strictEqual(storage.getLastEntryId(), null);
    });

    it('handles missing file', () => {
        const path = join(tempDir, 'missing.jsonl');
        const storage = new JsonlStorage(path);
        const map = storage.load();
        assert.strictEqual(map.size, 0);
        assert.strictEqual(storage.getLastEntryId(), null);
    });

    it('stops at corrupt line and truncates', async () => {
        const path = join(tempDir, 'corrupt.jsonl');
        const storage = new JsonlStorage(path);

        const entries = [
            makeMessage('msg1', null, 'A'),
            makeMessage('msg2', 'msg1', 'B'),
            makeMessage('msg3', 'msg2', 'C'),
            makeMessage('msg4', 'msg3', 'D'),
            makeMessage('msg5', 'msg4', 'E'),
        ];
        for (const e of entries) {
            storage.append(e);
        }

        const content = await readFile(path, 'utf-8');
        const lines = content.split('\n').filter(Boolean);
        const corrupted = JSON.parse(lines[3]);
        corrupted.content = 'CORRUPTED';
        lines[3] = JSON.stringify(corrupted);
        await writeFile(path, lines.join('\n') + '\n');

        const map = storage.load();
        assert.strictEqual(map.size, 3);
        assert.strictEqual(asMessageEntry(map.get('msg1')!).content, 'A');
        assert.strictEqual(asMessageEntry(map.get('msg2')!).content, 'B');
        assert.strictEqual(asMessageEntry(map.get('msg3')!).content, 'C');
        assert.strictEqual(map.get('msg4'), undefined);
        assert.strictEqual(map.get('msg5'), undefined);
        assert.strictEqual(storage.getLastEntryId(), 'msg3');

        const newContent = await readFile(path, 'utf-8');
        const newLines = newContent.split('\n').filter(Boolean);
        assert.strictEqual(newLines.length, 3);
        assert.ok(newContent.endsWith('\n'));
    });

    it('acquires and releases lock across instances', () => {
        const path = join(tempDir, 'lock.jsonl');
        const storage1 = new JsonlStorage(path);
        const storage2 = new JsonlStorage(path);

        storage1.lock();
        assert.throws(() => storage2.lock(), /Lock file exists/);
        storage1.unlock();
        storage2.lock();
        storage2.unlock();
    });

    it('releases lock even after append (verification)', () => {
        const path = join(tempDir, 'release.jsonl');
        const storage = new JsonlStorage(path);
        const entry = makeMessage('msg1', null, 'Hello');
        storage.append(entry);
        const storage2 = new JsonlStorage(path);
        storage2.lock();
        storage2.unlock();
    });

    it('handles malformed JSON', async () => {
        const path = join(tempDir, 'malformed.jsonl');
        const storage = new JsonlStorage(path);

        storage.append(makeMessage('msg1', null, 'A'));
        storage.append(makeMessage('msg2', 'msg1', 'B'));

        await writeFile(path, (await readFile(path, 'utf-8')) + 'not a json line\n');

        const map = storage.load();
        assert.strictEqual(map.size, 2);
        assert.strictEqual(storage.getLastEntryId(), 'msg2');

        const content = await readFile(path, 'utf-8');
        const lines = content.split('\n').filter(Boolean);
        assert.strictEqual(lines.length, 2);
    });

    it('getLastEntryId returns correct ID after load and after truncation', async () => {
        const path = join(tempDir, 'lastid.jsonl');
        const storage = new JsonlStorage(path);

        storage.append(makeMessage('msg1', null, 'A'));
        storage.append(makeMessage('msg2', 'msg1', 'B'));
        storage.append(makeMessage('msg3', 'msg2', 'C'));

        let map = storage.load();
        assert.strictEqual(storage.getLastEntryId(), 'msg3');

        const content = await readFile(path, 'utf-8');
        const lines = content.split('\n').filter(Boolean);
        const corrupted = JSON.parse(lines[2]);
        corrupted.content = 'CORRUPTED';
        lines[2] = JSON.stringify(corrupted);
        await writeFile(path, lines.join('\n') + '\n');

        map = storage.load();
        assert.strictEqual(storage.getLastEntryId(), 'msg2');
    });

    it('removes stale lock', async () => {
        const path = join(tempDir, 'stale.jsonl');
        const storage1 = new JsonlStorage(path, 10); // 10ms stale threshold
        storage1.lock();

        // Wait >10ms so the lock becomes stale
        await new Promise(resolve => setTimeout(resolve, 20));

        const storage2 = new JsonlStorage(path, 10);
        // Should not throw; should remove stale lock
        storage2.lock();
        assert.ok(existsSync(path + '.lock'));
        storage2.unlock();
    });

    it('append failure releases lock', () => {
        // Simulate failure by using a path to a non-existent directory
        const invalidPath = '/non/existent/dir/file.jsonl';
        const storage = new JsonlStorage(invalidPath);
        const entry = makeMessage('msg1', null, 'Hello');
        try {
            storage.append(entry);
            assert.fail('Should have thrown');
        } catch (_) {
            // Expected error
            // Lock should be released
            assert.strictEqual(storage['locked'], false);
        }
    });
});