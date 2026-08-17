// ts-cli/src/tree.ts
import { randomUUID } from 'node:crypto';
import type { Entry, MessageEntry, LeafEntry } from './types.js';
import { JsonlStorage } from './storage.js';

export class TreeEngine {
    private entries: Map<string, Entry> = new Map();
    private leafId: string | null = null;

    constructor(private storage: JsonlStorage) {}

    load(): void {
        this.entries = this.storage.load();
        this.leafId = this.storage.getLeafId();
    }

    getPathToRoot(leafId: string): Entry[] {
        const path: Entry[] = [];
        const visited = new Set<string>();
        let current = this.entries.get(leafId);

        if (!current) {
            throw new Error(`Leaf entry ${leafId} not found`);
        }

        while (current) {
            if (visited.has(current.id)) {
                throw new Error(`Cycle detected at entry ${current.id}`);
            }
            visited.add(current.id);
            path.unshift(current);

            if (!current.parentId) break;

            const parent = this.entries.get(current.parentId);
            if (!parent) {
                throw new Error(`Missing parent ${current.parentId} for entry ${current.id}`);
            }
            current = parent;
        }

        return path;
    }

    buildContext(leafId?: string): MessageEntry[] {
        const target = leafId ?? this.leafId;
        if (!target) return [];
        const path = this.getPathToRoot(target);
        return path.filter((e): e is MessageEntry => e.type === 'message');
    }

    moveLeaf(targetId: string): void {
        if (!this.entries.has(targetId)) {
            throw new Error(`Target entry ${targetId} does not exist`);
        }
        const leafEntry: LeafEntry = {
            id: `leaf-${Date.now()}-${randomUUID().slice(0, 8)}`,
            parentId: targetId,
            type: 'leaf',
            timestamp: Date.now(),
            checksum: '',
            targetId,
        };
        const persisted = this.storage.append(leafEntry);
        this.leafId = targetId;
        this.entries.set(persisted.id, persisted);
    }

    /**
     * Fork a new branch at the given node.
     * Copies the path from root to node, remints new IDs, appends the copied entries,
     * and moves the leaf to the new tip.
     * Returns the new leaf ID.
     */
    fork(nodeId: string): string {
        const path = this.getPathToRoot(nodeId);
        if (path.length === 0) {
            throw new Error(`Node ${nodeId} not found`);
        }

        const idMap = new Map<string, string>();
        const newEntries: Entry[] = [];

        // Create copies with new IDs and updated parent references
        for (const entry of path) {
            const newId = `fork-${Date.now()}-${randomUUID().slice(0, 8)}`;
            const newParentId = entry.parentId ? idMap.get(entry.parentId) || null : null;
            // Copy all fields except id, parentId, checksum (will be recomputed)
            const { id, parentId, checksum, ...rest } = entry;
            const newEntry: Entry = {
                ...rest,
                id: newId,
                parentId: newParentId,
                checksum: '', // will be recomputed by storage.append
            };
            newEntries.push(newEntry);
            idMap.set(entry.id, newId);
        }

        // Append all new entries in root-to-leaf order
        for (const newEntry of newEntries) {
            const persisted = this.storage.append(newEntry);
            this.entries.set(persisted.id, persisted);
        }

        // Move leaf to the last new entry (the tip of the fork)
        const lastNewId = newEntries[newEntries.length - 1].id;
        this.moveLeaf(lastNewId);
        return lastNewId;
    }

    getLeaf(): string | null {
        return this.leafId;
    }

    getEntry(id: string): Entry | undefined {
        return this.entries.get(id);
    }

    getAllEntries(): Map<string, Entry> {
        return this.entries;
    }
}