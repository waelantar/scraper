// src/types.test.ts
import { describe, it } from 'node:test';
import assert from 'node:assert';
import type { Entry, MessageEntry, LeafEntry } from './types.js';

function isMessageEntry(e: Entry): e is MessageEntry {
    return e.type === 'message';
}

describe('Entry types', () => {
    it('MessageEntry has correct shape', () => {
        const msg: MessageEntry = {
            id: 'msg1',
            parentId: null,
            type: 'message',
            timestamp: Date.now(),
            checksum: 'abc123',
            role: 'user',
            content: 'Hello',
        };
        assert.strictEqual(msg.type, 'message');
        assert.strictEqual(isMessageEntry(msg), true);
    });

    it('LeafEntry has correct shape', () => {
        const leaf: LeafEntry = {
            id: 'leaf1',
            parentId: 'msg1',
            type: 'leaf',
            timestamp: Date.now(),
            checksum: 'def456',
            targetId: 'msg1',
        };
        assert.strictEqual(leaf.type, 'leaf');
        assert.strictEqual(isMessageEntry(leaf), false);
    });

    // Negative test: TypeScript should reject a LeafEntry with a 'role' field.
    // The error fires on the property line, not the const assignment.
    it('should not allow role on LeafEntry (compile-time check)', () => {
        const invalid: LeafEntry = {
            id: 'leaf1',
            parentId: null,
            type: 'leaf',
            timestamp: Date.now(),
            checksum: 'abc',
            targetId: 't1',
            // @ts-expect-error - LeafEntry does not have a 'role' field
            role: 'user',
        };
        // The line above is suppressed by @ts-expect-error.
        // We never reach this point at runtime; the type-check script enforces it.
        assert.ok(true);
    });
});