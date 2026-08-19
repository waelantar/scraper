// ts-cli/src/tree-renderer.ts
import type { Entry, MessageEntry } from './types.js';

/**
 * Renders a session tree as indented ASCII.
 * Marks the current leaf with a `*` suffix.
 * Treats entries with missing parentId as orphans (rendered as roots).
 * Siblings sorted by timestamp, then ID.
 */
export function renderTree(
    entries: Map<string, Entry>,
    leafId: string | null
): string {
    if (entries.size === 0) {
        return '(empty tree)';
    }

    // Build children map
    const children = new Map<string, string[]>();
    for (const [id, entry] of entries) {
        const parent = entry.parentId || 'root';
        if (!children.has(parent)) children.set(parent, []);
        children.get(parent)!.push(id);
    }

    // Find roots:
    // - entries with null parentId
    // - entries whose parentId points to a missing ID (orphans)
    const roots: string[] = [];
    const existingIds = new Set(entries.keys());
    for (const [id, entry] of entries) {
        if (!entry.parentId) {
            roots.push(id);
        } else if (!existingIds.has(entry.parentId)) {
            // Orphan: parent doesn't exist
            roots.push(id);
        }
    }

    // Sort roots deterministically by timestamp, then ID
    roots.sort((a, b) => {
        const ea = entries.get(a)!;
        const eb = entries.get(b)!;
        if (ea.timestamp !== eb.timestamp) return ea.timestamp - eb.timestamp;
        return a.localeCompare(b);
    });

    const lines: string[] = [];
    const visited = new Set<string>();

    const printNode = (id: string, prefix: string, isLast: boolean) => {
        if (visited.has(id)) return;
        visited.add(id);
        const entry = entries.get(id);
        if (!entry) return;

        const isLeaf = id === leafId;
        const marker = isLeaf ? ' *' : '';
        let label: string;
        if (entry.type === 'message') {
            const msg = entry as MessageEntry;
            const contentPreview = msg.content.slice(0, 30);
            label = `${msg.role}: ${contentPreview}`;
        } else {
            label = entry.type;
        }
        const line = `${prefix}${isLast ? '└─ ' : '├─ '}${id} (${label})${marker}`;
        lines.push(line);

        const kids = children.get(id) || [];
        // Sort kids by timestamp, then ID
        kids.sort((a, b) => {
            const ea = entries.get(a)!;
            const eb = entries.get(b)!;
            if (ea.timestamp !== eb.timestamp) return ea.timestamp - eb.timestamp;
            return a.localeCompare(b);
        });
        for (let i = 0; i < kids.length; i++) {
            const isLastChild = i === kids.length - 1;
            const childPrefix = prefix + (isLast ? '    ' : '│   ');
            printNode(kids[i], childPrefix, isLastChild);
        }
    };

    for (let i = 0; i < roots.length; i++) {
        const isLastRoot = i === roots.length - 1;
        printNode(roots[i], '', isLastRoot);
    }

    return lines.join('\n');
}