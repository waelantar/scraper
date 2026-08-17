// ts-cli/src/fork.test.ts
import { describe, it, before, after } from 'node:test';
import assert from 'node:assert';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { JsonlStorage } from './storage.js';
import { TreeEngine } from './tree.js';
import type { MessageEntry } from './types.js';

describe('Fork', () => {
    let tempDir: string;

    before(async () => {
        tempDir = await mkdtemp(join(tmpdir(), 'fork-test-'));
    });

    after(async () => {
        await rm(tempDir, { recursive: true, force: true });
    });

    it('forks a branch at a node', () => {
        const path = join(tempDir, 'fork.jsonl');
        const storage = new JsonlStorage(path);
        const tree = new TreeEngine(storage);

        // Build tree: A -> B -> C
        const a: MessageEntry = {
            id: 'A',
            parentId: null,
            type: 'message',
            timestamp: Date.now(),
            checksum: '',
            role: 'user',
            content: 'Root'
        };
        const b: MessageEntry = {
            id: 'B',
            parentId: 'A',
            type: 'message',
            timestamp: Date.now(),
            checksum: '',
            role: 'user',
            content: 'Child'
        };
        const c: MessageEntry = {
            id: 'C',
            parentId: 'B',
            type: 'message',
            timestamp: Date.now(),
            checksum: '',
            role: 'user',
            content: 'Leaf'
        };

        storage.append(a);
        storage.append(b);
        storage.append(c);
        tree.load();
        tree.moveLeaf('C');

        // Fork at B
        const newLeafId = tree.fork('B');

        // Verify leaf moved to new fork tip
        assert.strictEqual(tree.getLeaf(), newLeafId);

        // Verify new branch entries exist
        const pathToNew = tree.getPathToRoot(newLeafId);
        assert.strictEqual(pathToNew.length, 2);
        assert.notStrictEqual(pathToNew[0].id, 'A'); // new root ID
        assert.notStrictEqual(pathToNew[1].id, 'B'); // new child ID
        assert.strictEqual(pathToNew[0].parentId, null);
        assert.strictEqual(pathToNew[1].parentId, pathToNew[0].id);
        assert.strictEqual((pathToNew[0] as MessageEntry).content, 'Root');
        assert.strictEqual((pathToNew[1] as MessageEntry).content, 'Child');

        // Verify original C still exists
        const originalC = tree.getEntry('C');
        assert.ok(originalC);
        assert.strictEqual(originalC.type, 'message');

        // Verify buildContext returns new branch messages
        const context = tree.buildContext();
        assert.strictEqual(context.length, 2);
        assert.strictEqual(context[0].content, 'Root');
        assert.strictEqual(context[1].content, 'Child');
    });

    it('forks at root', () => {
        const path = join(tempDir, 'fork-root.jsonl');
        const storage = new JsonlStorage(path);
        const tree = new TreeEngine(storage);

        const a: MessageEntry = {
            id: 'A',
            parentId: null,
            type: 'message',
            timestamp: Date.now(),
            checksum: '',
            role: 'user',
            content: 'Root'
        };
        storage.append(a);
        tree.load();
        tree.moveLeaf('A');

        const newLeafId = tree.fork('A');
        assert.strictEqual(tree.getLeaf(), newLeafId);
        const pathToNew = tree.getPathToRoot(newLeafId);
        assert.strictEqual(pathToNew.length, 1);
        assert.notStrictEqual(pathToNew[0].id, 'A');
        assert.strictEqual(pathToNew[0].parentId, null);
        assert.strictEqual((pathToNew[0] as MessageEntry).content, 'Root');

        // Original A still exists
        assert.ok(tree.getEntry('A'));
    });
});