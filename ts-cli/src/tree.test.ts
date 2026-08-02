// ts-cli/src/tree.test.ts
import { describe, it, before, after } from 'node:test';
import assert from 'node:assert';
import { mkdtemp, rm, readFile, writeFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createHash } from 'node:crypto';
import { JsonlStorage } from './storage.js';
import { TreeEngine } from './tree.js';
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

function asMessage(e: Entry): MessageEntry {
    assert.strictEqual(e.type, 'message');
    return e as MessageEntry;
}

describe('TreeEngine', () => {
    let tempDir: string;

    before(async () => {
        tempDir = await mkdtemp(join(tmpdir(), 'tree-test-'));
    });

    after(async () => {
        await rm(tempDir, { recursive: true, force: true });
    });

    it('loads empty storage', () => {
        const path = join(tempDir, 'empty.jsonl');
        const storage = new JsonlStorage(path);
        const tree = new TreeEngine(storage);
        tree.load();
        assert.strictEqual(tree.getLeaf(), null);
        assert.throws(() => tree.getPathToRoot('missing'), /not found/);
        assert.deepStrictEqual(tree.buildContext(), []);
    });

    it('builds path A->B->C', () => {
        const path = join(tempDir, 'abc.jsonl');
        const storage = new JsonlStorage(path);
        const tree = new TreeEngine(storage);

        const a = makeMessage('A', null, 'Root');
        const b = makeMessage('B', 'A', 'Child');
        const c = makeMessage('C', 'B', 'Grandchild');

        storage.append(a);
        storage.append(b);
        storage.append(c);

        tree.load();

        tree.moveLeaf('C');
        assert.strictEqual(tree.getLeaf(), 'C');

        const rootPath = tree.getPathToRoot('C');
        assert.strictEqual(rootPath.length, 3);
        assert.strictEqual(rootPath[0].id, 'A');
        assert.strictEqual(rootPath[1].id, 'B');
        assert.strictEqual(rootPath[2].id, 'C');

        const msgs = tree.buildContext('C');
        assert.strictEqual(msgs.length, 3);
        assert.strictEqual(asMessage(msgs[0]).content, 'Root');
        assert.strictEqual(asMessage(msgs[1]).content, 'Child');
        assert.strictEqual(asMessage(msgs[2]).content, 'Grandchild');
    });

    it('persists leaf across reload', () => {
        const path = join(tempDir, 'persist.jsonl');
        const storage1 = new JsonlStorage(path);
        const tree1 = new TreeEngine(storage1);

        const a = makeMessage('A', null, 'Root');
        const b = makeMessage('B', 'A', 'Child');
        storage1.append(a);
        storage1.append(b);

        tree1.load();
        tree1.moveLeaf('B');

        const storage2 = new JsonlStorage(path);
        const tree2 = new TreeEngine(storage2);
        tree2.load();

        assert.strictEqual(tree2.getLeaf(), 'B');
        const path2 = tree2.getPathToRoot('B');
        assert.strictEqual(path2.length, 2);
        assert.strictEqual(path2[0].id, 'A');
        assert.strictEqual(path2[1].id, 'B');
    });

    it('supports branching A->B->C and A->D', () => {
        const path = join(tempDir, 'branch.jsonl');
        const storage = new JsonlStorage(path);
        const tree = new TreeEngine(storage);

        const a = makeMessage('A', null, 'Root');
        const b = makeMessage('B', 'A', 'Branch1');
        const c = makeMessage('C', 'B', 'Leaf1');
        const d = makeMessage('D', 'A', 'Branch2');

        storage.append(a);
        storage.append(b);
        storage.append(c);
        storage.append(d);

        tree.load();

        // Leaf should be null (no leaf entry yet)
        assert.strictEqual(tree.getLeaf(), null);

        tree.moveLeaf('C');
        let pathC = tree.getPathToRoot('C');
        assert.strictEqual(pathC.length, 3);
        assert.strictEqual(pathC[0].id, 'A');
        assert.strictEqual(pathC[1].id, 'B');
        assert.strictEqual(pathC[2].id, 'C');

        tree.moveLeaf('D');
        let pathD = tree.getPathToRoot('D');
        assert.strictEqual(pathD.length, 2);
        assert.strictEqual(pathD[0].id, 'A');
        assert.strictEqual(pathD[1].id, 'D');

        const storage2 = new JsonlStorage(path);
        const tree2 = new TreeEngine(storage2);
        tree2.load();
        assert.strictEqual(tree2.getLeaf(), 'D');
    });

    it('throws on missing parent', () => {
        const path = join(tempDir, 'corrupt.jsonl');
        const storage = new JsonlStorage(path);
        const tree = new TreeEngine(storage);

        const orphan = makeMessage('orphan', 'missing-parent', 'Orphan');
        storage.append(orphan);
        tree.load();

        assert.throws(() => tree.getPathToRoot('orphan'), /Missing parent/);
    });

    it('throws on cycle detection', async () => {
        const path = join(tempDir, 'cycle.jsonl');
        const storage = new JsonlStorage(path);
        const tree = new TreeEngine(storage);

        const a = makeMessage('A', null, 'Root');
        const b = makeMessage('B', 'A', 'Child');
        const c = makeMessage('C', 'B', 'Grandchild');

        storage.append(a);
        storage.append(b);
        storage.append(c);

        // Manually corrupt the file to create a cycle
        const content = await readFile(path, 'utf-8');
        const lines = content.split('\n').filter(Boolean);
        
        // Parse and modify A to point to C
        const aEntry = JSON.parse(lines[0]);
        aEntry.parentId = 'C'; // A → C creates cycle: A → C → B → A
        
        // Recompute checksum for A
        const { checksum: _, ...payload } = aEntry;
        aEntry.checksum = createHash('sha256')
            .update(JSON.stringify(payload))
            .digest('hex');
        
        lines[0] = JSON.stringify(aEntry);
        await writeFile(path, lines.join('\n') + '\n');

        // Reload with fresh storage
        const storage2 = new JsonlStorage(path);
        const tree2 = new TreeEngine(storage2);
        tree2.load();

        // The cycle should be detected when traversing
        assert.throws(() => tree2.getPathToRoot('A'), /Cycle detected/);
        assert.throws(() => tree2.getPathToRoot('C'), /Cycle detected/);
        assert.throws(() => tree2.getPathToRoot('B'), /Cycle detected/);
    });
});