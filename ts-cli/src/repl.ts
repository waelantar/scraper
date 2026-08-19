// ts-cli/src/repl.ts
import { createInterface } from 'node:readline/promises';
import { DatabaseSync } from 'node:sqlite';
import type { TreeEngine } from './tree.js';
import type { MessageEntry } from './types.js';
import { renderTree } from './tree-renderer.js';

export class Repl {
    private rl = createInterface({
        input: process.stdin,
        output: process.stdout,
        terminal: true,
    });
    private db: DatabaseSync | null = null;

    constructor(
        private tree: TreeEngine,
        private dbPath: string,
    ) {}

    private getDb(): DatabaseSync {
        if (!this.db) {
            this.db = new DatabaseSync(this.dbPath);
        }
        return this.db;
    }

    async run(): Promise<void> {
        console.log('🔍 pi CLI — branchable conversation tree');
        console.log('Type a message to append, or use /commands: /query, /view, /fork, /tree, /status, /exit');
        console.log('');

        try {
            while (true) {
                const line = await this.rl.question('> ');
                const trimmed = line.trim();
                if (trimmed === '') continue;

                if (trimmed === '/exit') {
                    break;
                }

                if (trimmed.startsWith('/')) {
                    await this.handleCommand(trimmed);
                } else {
                    await this.appendMessage(trimmed);
                }
            }
        } catch (err) {
            console.log('Error:', (err as Error).message);
        } finally {
            this.rl.close();
            if (this.db) {
                this.db.close();
            }
            console.log('Goodbye.');
        }
    }

    private async handleCommand(raw: string): Promise<void> {
        const parts = raw.split(/\s+/);
        const cmd = parts[0].toLowerCase();
        const args = parts.slice(1);

        switch (cmd) {
            case '/query': {
                const search = args.join(' ');
                if (!search) {
                    console.log('Usage: /query <text>');
                    return;
                }
                this.queryCrawledDB(search);
                break;
            }
            case '/view': {
                const url = args[0];
                if (!url) {
                    console.log('Usage: /view <url>');
                    return;
                }
                this.viewCrawledPage(url);
                break;
            }
            case '/fork': {
                const nodeId = args[0];
                if (!nodeId) {
                    console.log('Usage: /fork <entryId>');
                    return;
                }
                try {
                    const newLeafId = this.tree.fork(nodeId);
                    console.log(`✅ Forked at ${nodeId}, new leaf: ${newLeafId}`);
                } catch (err) {
                    console.log(`❌ Fork failed: ${(err as Error).message}`);
                }
                break;
            }
            case '/tree': {
                this.renderTree();
                break;
            }
            case '/status': {
                this.showStatus();
                break;
            }
            default:
                console.log(`Unknown command: ${cmd}. Available: /query, /view, /fork, /tree, /status, /exit`);
        }
    }

    private async appendMessage(text: string): Promise<void> {
        const parentId = this.tree.getLeaf();
        const entry: MessageEntry = {
            id: `msg-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
            parentId,
            type: 'message',
            timestamp: Date.now(),
            checksum: '',
            role: 'user',
            content: text,
        };
        const persisted = this.tree.appendMessage(entry);
        console.log(`✅ Message appended (id: ${persisted.id})`);
    }

    private queryCrawledDB(search: string): void {
        try {
            const stmt = this.getDb().prepare(
                `SELECT url, title, content FROM pages
                 WHERE content LIKE ? OR title LIKE ?
                 LIMIT 20`
            );
            const rows = stmt.all(`%${search}%`, `%${search}%`) as Array<{ url: string; title: string | null; content: string | null }>;
            if (rows.length === 0) {
                console.log('No matches found.');
                return;
            }
            console.log(`Found ${rows.length} pages:`);
            for (const row of rows) {
                console.log(`  ${row.url} — ${row.title || 'no title'}`);
            }
        } catch (err) {
            console.log(`❌ Query error: ${(err as Error).message}`);
        }
    }

    private viewCrawledPage(url: string): void {
        try {
            const stmt = this.getDb().prepare(
                `SELECT url, title, content, status_code FROM pages WHERE url = ?`
            );
            const row = stmt.get(url) as { url: string; title: string | null; content: string | null; status_code: number } | undefined;
            if (!row) {
                console.log('Page not found in cache.');
                return;
            }
            console.log(`URL: ${row.url}`);
            console.log(`Title: ${row.title || '(none)'}`);
            console.log(`Status: ${row.status_code}`);
            console.log('--- Content ---');
            const content = row.content || '(empty)';
            console.log(content.slice(0, 1000));
            if (content.length > 1000) {
                console.log('... (truncated)');
            }
        } catch (err) {
            console.log(`❌ View error: ${(err as Error).message}`);
        }
    }

    private renderTree(): void {
    const allEntries = this.tree.getAllEntries();
    const leaf = this.tree.getLeaf();
    const output = renderTree(allEntries, leaf);
    console.log(output);
}

    private showStatus(): void {
        const all = this.tree.getAllEntries();
        const leaf = this.tree.getLeaf();
        console.log(`Entries: ${all.size}`);
        console.log(`Leaf: ${leaf || '(none)'}`);
        console.log(`Session: ${this.tree.getSessionPath()}`);
        console.log(`Database: ${this.dbPath}`);
    }
}