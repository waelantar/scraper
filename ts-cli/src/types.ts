// ts-cli/src/types.ts

/**
 * Every entry in the append‑only journal shares these fields.
 * `id` is globally unique (preferably time‑sortable).
 * `parentId` points to the previous entry; `null` means root.
 * `type` discriminates the union.
 * `timestamp` is the creation time (milliseconds since epoch).
 * `checksum` is a hash of the entry's payload (for crash‑safety).
 */
export interface BaseEntry {
    id: string;
    parentId: string | null;
    type: string;
    timestamp: number;
    checksum: string;
}

/** A user or assistant message */
export interface MessageEntry extends BaseEntry {
    type: 'message';
    role: 'user' | 'assistant' | 'tool';
    content: string;
    // optional: tool calls, tool results, etc. (add later)
}

/** A persisted leaf move (where the conversation pointer is) */
export interface LeafEntry extends BaseEntry {
    type: 'leaf';
    targetId: string;   // points to the entry that is now the leaf
}

/** A compaction boundary (context‑window summary) */
export interface CompactionEntry extends BaseEntry {
    type: 'compaction';
    summary: string;
    firstKeptEntryId: string;
    tokensBefore: number;
}

/** A summary of an abandoned branch */
export interface BranchSummaryEntry extends BaseEntry {
    type: 'branch_summary';
    fromId: string;       // where you left
    summary: string;
    details?: string;     // optional extra info
}

/** A model change (positional config) */
export interface ModelChangeEntry extends BaseEntry {
    type: 'model_change';
    model: string;
}

/** A thinking‑level change (positional config) */
export interface ThinkingLevelChangeEntry extends BaseEntry {
    type: 'thinking_level_change';
    level: number;
}

/** An active‑tools change (positional config) */
export interface ActiveToolsChangeEntry extends BaseEntry {
    type: 'active_tools_change';
    tools: string[];
}

/** A user label on an entry */
export interface LabelEntry extends BaseEntry {
    type: 'label';
    targetId: string;
    label: string;
}

/** Session rename (legacy) */
export interface SessionInfoEntry extends BaseEntry {
    type: 'session_info';
    name: string;
}

/** Extension‑authored entry */
export interface CustomEntry extends BaseEntry {
    type: 'custom';
    payload: unknown;   // extension‑specific
}

export type Entry =
    | MessageEntry
    | LeafEntry
    | CompactionEntry
    | BranchSummaryEntry
    | ModelChangeEntry
    | ThinkingLevelChangeEntry
    | ActiveToolsChangeEntry
    | LabelEntry
    | SessionInfoEntry
    | CustomEntry;