// ts-cli/src/tree-renderer.test.ts
import { describe, it } from 'node:test';
import assert from 'node:assert';
import { renderTree } from './tree-renderer.js';
import type { MessageEntry } from './types.js';

function makeMessage(
    id: string,
    parentId: string | null,
    content: string,
    timestamp: number = Date.now(),
    role: 'user' | 'assistant' = 'user'
): MessageEntry {
    return {
        id,
        parentId,
        type: 'message',
        timestamp,
        checksum: '',
        role,
        content,
    };
}

describe('TreeRenderer', () => {
    it('renders a simple linear tree', () => {
        const entries = new Map();
        const t0 = 1000;
        const a = makeMessage('A', null, 'Root', t0);
        const b = makeMessage('B', 'A', 'Child', t0 + 1);
        const c = makeMessage('C', 'B', 'Grandchild', t0 + 2);
        entries.set('A', a);
        entries.set('B', b);
        entries.set('C', c);

        const output = renderTree(entries, 'C');
        const expected = [
            '└─ A (user: Root)',
            '    └─ B (user: Child)',
            '        └─ C (user: Grandchild) *',
        ].join('\n');
        assert.strictEqual(output, expected);
    });

    it('renders branching tree with leaf marker', () => {
        const entries = new Map();
        const t0 = 1000;
        const a = makeMessage('A', null, 'Root', t0);
        const b = makeMessage('B', 'A', 'Branch1', t0 + 1);
        const c = makeMessage('C', 'B', 'Leaf1', t0 + 2);
        const d = makeMessage('D', 'A', 'Branch2', t0 + 3);
        entries.set('A', a);
        entries.set('B', b);
        entries.set('C', c);
        entries.set('D', d);

        const output = renderTree(entries, 'D');
        const expected = [
            '└─ A (user: Root)',
            '    ├─ B (user: Branch1)',
            '    │   └─ C (user: Leaf1)',
            '    └─ D (user: Branch2) *',
        ].join('\n');
        assert.strictEqual(output, expected);
    });

    it('renders multiple roots with correct connectors', () => {
        const entries = new Map();
        const t0 = 1000;
        const a = makeMessage('A', null, 'Root A', t0);
        const b = makeMessage('B', null, 'Root B', t0 + 1);
        entries.set('A', a);
        entries.set('B', b);

        const output = renderTree(entries, 'B');
        // First root uses ├─, last root uses └─
        const expected = [
            '├─ A (user: Root A)',
            '└─ B (user: Root B) *',
        ].join('\n');
        assert.strictEqual(output, expected);
    });

    it('handles empty tree', () => {
        const entries = new Map();
        const output = renderTree(entries, null);
        assert.strictEqual(output, '(empty tree)');
    });

    it('handles orphaned entries (parentId pointing to missing id)', () => {
        const entries = new Map();
        const orphan = makeMessage('orphan', 'missing-parent', 'Orphan');
        entries.set('orphan', orphan);

        const output = renderTree(entries, 'orphan');
        // Orphan should be rendered as a root
        const expected = ['└─ orphan (user: Orphan) *'].join('\n');
        assert.strictEqual(output, expected);
    });

    it('sorts siblings by timestamp then ID', () => {
        const entries = new Map();
        const t0 = 1000;
        const a = makeMessage('A', null, 'Root', t0);
        const b = makeMessage('B', 'A', 'B', t0 + 5);
        const c = makeMessage('C', 'A', 'C', t0 + 2);
        const d = makeMessage('D', 'A', 'D', t0 + 3);
        entries.set('A', a);
        entries.set('B', b);
        entries.set('C', c);
        entries.set('D', d);

        const output = renderTree(entries, 'D');
        // Expected order: C (t+2), D (t+3), B (t+5)
        const expected = [
            '└─ A (user: Root)',
            '    ├─ C (user: C)',
            '    ├─ D (user: D) *',
            '    └─ B (user: B)',
        ].join('\n');
        assert.strictEqual(output, expected);
    });
});