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

    fork(nodeId: string): string {
        const path = this.getPathToRoot(nodeId);
        if (path.length === 0) {
            throw new Error(`Node ${nodeId} not found`);
        }

        const idMap = new Map<string, string>();
        const newEntries: Entry[] = [];

        for (const entry of path) {
            const newId = `fork-${Date.now()}-${randomUUID().slice(0, 8)}`;
            const newParentId = entry.parentId ? idMap.get(entry.parentId) || null : null;
            const { id, parentId, checksum, ...rest } = entry;
            const newEntry: Entry = {
                ...rest,
                id: newId,
                parentId: newParentId,
                checksum: '',
            };
            newEntries.push(newEntry);
            idMap.set(entry.id, newId);
        }

        for (const newEntry of newEntries) {
            const persisted = this.storage.append(newEntry);
            this.entries.set(persisted.id, persisted);
        }

        const lastNewId = newEntries[newEntries.length - 1].id;
        this.moveLeaf(lastNewId);
        return lastNewId;
    }

    /** Append a message and move the leaf to it. */
    appendMessage(entry: MessageEntry): Entry {
        const persisted = this.storage.append(entry);
        this.entries.set(persisted.id, persisted);
        this.moveLeaf(persisted.id);
        return persisted;
    }

    /** Get the session file path. */
    getSessionPath(): string {
        return this.storage['filePath'];
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