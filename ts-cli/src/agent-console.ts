import { spawn } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { DatabaseSync } from 'node:sqlite';
import { isAbsolute, join } from 'node:path';
import { createInterface } from 'node:readline/promises';
import type { TreeEngine } from './tree.js';
import type { MessageEntry } from './types.js';
import { renderTree } from './tree-renderer.js';

type Output = (text: string) => void;

interface CrawlerStats {
    attempted: number;
    crawled: number;
    errors: number;
    skipped_robots: number;
}

export interface CrawlerRunOutcome {
    state: 'success' | 'partial' | 'cached' | 'robots' | 'failed';
    result: string;
    guidance: string;
}

export type AgentCommand =
    | { kind: 'crawl'; seed: string; options: string[] }
    | { kind: 'query'; search: string }
    | { kind: 'view'; url: string }
    | { kind: 'note'; content: string }
    | { kind: 'fork'; nodeId: string }
    | { kind: 'tree' }
    | { kind: 'status' }
    | { kind: 'help' }
    | { kind: 'clear' }
    | { kind: 'exit' }
    | { kind: 'invalid'; message: string };

const colors = {
    reset: '\u001b[0m',
    dim: '\u001b[2m',
    cyan: '\u001b[36m',
    green: '\u001b[32m',
    yellow: '\u001b[33m',
    red: '\u001b[31m',
    bold: '\u001b[1m',
};

const useColor = Boolean(process.stdout.isTTY);
const interactiveTerminal = Boolean(process.stdin.isTTY && process.stdout.isTTY);

function paint(text: string, ...styles: string[]): string {
    if (!useColor) return text;
    return `${styles.join('')}${text}${colors.reset}`;
}

function rule(): string {
    return paint('─'.repeat(70), colors.dim);
}

function pluralize(count: number, noun: string): string {
    return `${count} ${noun}${count === 1 ? '' : 's'}`;
}

/** Keep HTML title whitespace from breaking terminal result rows. */
export function normalizeTerminalText(text: string): string {
    return text.replace(/\s+/g, ' ').trim();
}

/**
 * Extract the final stats object emitted by `python -m python_engine crawl`.
 * Crawler logs are streamed live, so parsing happens from the full captured
 * output only after the child process exits.
 */
export function parseCrawlerStats(output: string): CrawlerStats | null {
    const match = output.match(/\{\s*"attempted"\s*:\s*\d+[\s\S]*?\}/);
    if (!match) return null;

    try {
        const value = JSON.parse(match[0]) as Partial<CrawlerStats>;
        if (
            typeof value.attempted !== 'number'
            || typeof value.crawled !== 'number'
            || typeof value.errors !== 'number'
            || typeof value.skipped_robots !== 'number'
        ) {
            return null;
        }
        return {
            attempted: value.attempted,
            crawled: value.crawled,
            errors: value.errors,
            skipped_robots: value.skipped_robots,
        };
    } catch {
        return null;
    }
}

/** Return a user-facing outcome based on both process status and crawl stats. */
export function describeCrawlerRun(exitCode: number, output: string): CrawlerRunOutcome {
    if (exitCode !== 0) {
        return {
            state: 'failed',
            result: `Crawler exited with code ${exitCode}`,
            guidance: 'Read the crawler output above, correct the problem, then try again.',
        };
    }

    const stats = parseCrawlerStats(output);
    if (!stats) {
        return {
            state: 'success',
            result: 'Crawler finished',
            guidance: 'Try search <text> to inspect the cache.',
        };
    }

    if (stats.errors > 0) {
        return {
            state: 'partial',
            result: `Crawler completed with ${pluralize(stats.errors, 'fetch error')} and ${pluralize(stats.crawled, 'new page')}.`,
            guidance: 'Open the seed URL to inspect the cached response and status code.',
        };
    }

    if (stats.crawled === 0 && stats.skipped_robots > 0) {
        return {
            state: 'robots',
            result: `Crawler finished — ${pluralize(stats.skipped_robots, 'URL')} blocked by robots.txt.`,
            guidance: 'Choose an allowed URL or review the site’s crawl rules.',
        };
    }

    if (stats.crawled === 0) {
        return {
            state: 'cached',
            result: 'Crawler finished — no new pages were fetched.',
            guidance: 'The seed may already be cached; use a new --db-path to crawl it again.',
        };
    }

    return {
        state: 'success',
        result: `Crawler finished — ${pluralize(stats.crawled, 'new page')} cached.`,
        guidance: 'Try search <text> to inspect the cache.',
    };
}

function centeredBoxLine(content: string, ...styles: string[]): string {
    const innerWidth = 68;
    const remaining = Math.max(0, innerWidth - content.length);
    const leftPadding = Math.floor(remaining / 2);
    const rightPadding = remaining - leftPadding;
    return paint('│', colors.cyan)
        + ' '.repeat(leftPadding)
        + paint(content, ...styles)
        + ' '.repeat(rightPadding)
        + paint('│', colors.cyan);
}

/**
 * Parse the deliberately small command language used by the agent terminal.
 * Slash commands remain accepted so existing CLI muscle memory still works.
 * Any non-command input becomes a persisted research note.
 */
export function parseAgentCommand(input: string): AgentCommand {
    const trimmed = input.trim();
    if (!trimmed) {
        return { kind: 'invalid', message: 'Type a command or a note. Try help.' };
    }

    const [rawVerb, ...parts] = trimmed.split(/\s+/);
    const verb = rawVerb.toLowerCase().replace(/^\//, '');
    const rest = parts.join(' ').trim();

    switch (verb) {
        case 'crawl': {
            const [seed, ...options] = parts;
            if (!seed || !/^https?:\/\//i.test(seed)) {
                return { kind: 'invalid', message: 'Usage: crawl <https://site.example> [crawler options]' };
            }
            return { kind: 'crawl', seed, options };
        }
        case 'search':
        case 'find':
        case 'query':
            return rest
                ? { kind: 'query', search: rest }
                : { kind: 'invalid', message: 'Usage: search <text>' };
        case 'open':
        case 'view':
            return rest
                ? { kind: 'view', url: rest }
                : { kind: 'invalid', message: 'Usage: open <cached URL>' };
        case 'note':
            return rest
                ? { kind: 'note', content: rest }
                : { kind: 'invalid', message: 'Usage: note <observation>' };
        case 'branch':
        case 'fork':
            return rest
                ? { kind: 'fork', nodeId: rest }
                : { kind: 'invalid', message: 'Usage: branch <message-id>' };
        case 'tree':
            return { kind: 'tree' };
        case 'status':
            return { kind: 'status' };
        case 'help':
            return { kind: 'help' };
        case 'clear':
            return { kind: 'clear' };
        case 'exit':
        case 'quit':
            return { kind: 'exit' };
        default:
            return { kind: 'note', content: trimmed };
    }
}

/** A dependency-free wordmark that remains readable in ordinary Windows Terminal. */
export function renderBanner(): string {
    const wordmark = [
        '████  ███  █     █   █  ████ █      ███  █████',
        '█   █ █   █ █     █ █  █     █     █   █   █  ',
        '████  █   █ █      █   █  ██ █     █   █   █  ',
        '█     █   █ █      █   █   █ █     █   █   █  ',
        '█      ███  █████  █    ███  █████  ███    █  ',
    ];
    const subtitle = 'Local research agent  ·  crawl, search, investigate, branch';
    const hint = paint('Type ', colors.dim)
        + paint('help', colors.green, colors.bold)
        + paint(' to see actions. Plain text becomes a durable note.', colors.dim);

    return [
        '',
        paint('╭────────────────────────────────────────────────────────────────────╮', colors.cyan),
        ...wordmark.map((line) => centeredBoxLine(line, colors.bold, colors.cyan)),
        centeredBoxLine(subtitle, colors.dim),
        paint('╰────────────────────────────────────────────────────────────────────╯', colors.cyan),
        hint,
        '',
    ].join('\n');
}

export interface AgentConsoleOptions {
    tree: TreeEngine;
    dbPath: string;
    projectRoot: string;
    pythonExecutable?: string;
    output?: Output;
}

/**
 * A focused terminal facade over the crawler, the SQLite cache, and the
 * branchable JSONL journal. It deliberately uses no terminal UI dependency.
 */
export class AgentConsole {
    private readonly rl = createInterface({
        input: process.stdin,
        output: process.stdout,
        terminal: interactiveTerminal,
    });
    private db: DatabaseSync | null = null;
    private dbPath: string;
    private readonly write: Output;
    private readonly pythonExecutable: string;

    constructor(private readonly options: AgentConsoleOptions) {
        this.dbPath = options.dbPath;
        this.write = options.output ?? ((text) => console.log(text));
        this.pythonExecutable = options.pythonExecutable ?? process.env.PYTHON_EXE ?? 'python';
    }

    async run(): Promise<void> {
        this.write(renderBanner());
        this.showQuickStart();

        try {
            if (interactiveTerminal) {
                await this.runInteractive();
            } else {
                await this.runPiped();
            }
        } catch (error) {
            this.write(`${paint('✕', colors.red, colors.bold)} ${(error as Error).message}`);
        } finally {
            this.rl.close();
            this.closeDb();
            this.write(paint('Session saved. Goodbye.', colors.dim));
        }
    }

    private async runInteractive(): Promise<void> {
        while (true) {
                const input = await this.rl.question(paint('polyglot ❯ ', colors.cyan, colors.bold));
                const command = parseAgentCommand(input);
                const shouldExit = await this.execute(command);
                if (shouldExit) break;
        }
    }

    private async runPiped(): Promise<void> {
        for await (const input of this.rl) {
            const command = parseAgentCommand(input);
            const shouldExit = await this.execute(command);
            if (shouldExit) break;
        }
    }

    async execute(command: AgentCommand): Promise<boolean> {
        switch (command.kind) {
            case 'crawl':
                await this.crawl(command.seed, command.options);
                return false;
            case 'query':
                this.query(command.search);
                return false;
            case 'view':
                this.view(command.url);
                return false;
            case 'note':
                this.saveNote(command.content);
                return false;
            case 'fork':
                this.fork(command.nodeId);
                return false;
            case 'tree':
                this.showTree();
                return false;
            case 'status':
                this.showStatus();
                return false;
            case 'help':
                this.showHelp();
                return false;
            case 'clear':
                console.clear();
                this.write(renderBanner());
                this.showQuickStart();
                return false;
            case 'exit':
                return true;
            case 'invalid':
                this.write(`${paint('!', colors.yellow, colors.bold)} ${command.message}`);
                return false;
        }
    }

    private showQuickStart(): void {
        this.write([
            `${paint('Quick start', colors.bold)}  ${paint('crawl https://books.toscrape.com/ --max-depth 1 --max-urls 20 --db-path data/books-demo.db', colors.green)}`,
            `${paint('Then', colors.bold)}         ${paint('search Himalayas  ·  open <url>  ·  write a plain-text observation', colors.dim)}`,
            rule(),
        ].join('\n'));
    }

    private showHelp(): void {
        this.write([
            paint('AVAILABLE ACTIONS', colors.bold, colors.cyan),
            '',
            `${paint('crawl <url> [options]', colors.green)}  Run the Python crawler and stream its output here.`,
            `${paint('search <text>', colors.green)}          Search titles and captured page text in SQLite.`,
            `${paint('open <url>', colors.green)}             Show a cached page preview.`,
            `${paint('note <text>', colors.green)}            Save an observation; plain text does the same thing.`,
            `${paint('branch <message-id>', colors.green)}    Copy a path into a new research branch.`,
            `${paint('tree', colors.green)}                   Draw branches and mark the active leaf.`,
            `${paint('status', colors.green)}                 Show session and database paths.`,
            `${paint('clear', colors.green)}                  Redraw the terminal.`,
            `${paint('exit', colors.green)}                   Save and close.`,
            '',
            paint('Aliases: /query, /view, /fork, /tree, /status, /exit.', colors.dim),
            rule(),
        ].join('\n'));
    }

    private async crawl(seed: string, options: string[]): Promise<void> {
        const nextDbPath = this.getRequestedDbPath(options);
        if (nextDbPath !== this.dbPath) {
            this.closeDb();
            this.dbPath = nextDbPath;
        }

        this.write(`${paint('●', colors.cyan)} ${paint('Crawler started', colors.bold)} ${paint(seed, colors.dim)}`);
        this.write(paint(`  Python is writing to ${this.dbPath}`, colors.dim));

        const args = ['-m', 'python_engine', 'crawl', '--seed', seed, ...options];
        let crawlerStdout = '';
        const exitCode = await new Promise<number>((resolve, reject) => {
            const child = spawn(this.pythonExecutable, args, {
                cwd: this.options.projectRoot,
                env: process.env,
                stdio: ['ignore', 'pipe', 'pipe'],
                windowsHide: true,
            });

            const recordCrawlerOutput = (data: Buffer, captureForStats = false): void => {
                const raw = data.toString();
                if (captureForStats) crawlerStdout += raw;
                this.writeCrawlerOutput(raw);
            };
            child.stdout.on('data', (data: Buffer) => recordCrawlerOutput(data, true));
            child.stderr.on('data', (data: Buffer) => recordCrawlerOutput(data));
            child.once('error', reject);
            child.once('close', (code) => resolve(code ?? 1));
        });

        const outcome = describeCrawlerRun(exitCode, crawlerStdout);
        const marker = outcome.state === 'success'
            ? paint('✓', colors.green, colors.bold)
            : outcome.state === 'failed'
                ? paint('✕', colors.red, colors.bold)
                : paint('!', colors.yellow, colors.bold);
        this.write(`${marker} ${paint(outcome.result, colors.bold)} ${paint(outcome.guidance, colors.dim)}`);
        this.write(rule());
    }

    private writeCrawlerOutput(raw: string): void {
        for (const line of raw.split(/\r?\n/)) {
            if (line.trim()) {
                this.write(`${paint('│', colors.dim)} ${paint(line, colors.dim)}`);
            }
        }
    }

    private query(search: string): void {
        try {
            const statement = this.getDb().prepare(
                `SELECT url, title FROM pages
                 WHERE content LIKE ? OR title LIKE ?
                 LIMIT 20`
            );
            const rows = statement.all(`%${search}%`, `%${search}%`) as Array<{ url: string; title: string | null }>;
            if (rows.length === 0) {
                this.write(`${paint('○', colors.yellow)} No cached pages match ${paint(search, colors.bold)}.`);
                return;
            }

            this.write(`${paint('✓', colors.green, colors.bold)} ${paint(`${rows.length} cached page${rows.length === 1 ? '' : 's'} found`, colors.bold)} ${paint(`for “${search}”`, colors.dim)}`);
            rows.forEach((row, index) => {
                this.write(`  ${paint(String(index + 1).padStart(2, '0'), colors.cyan)}  ${normalizeTerminalText(row.title || '(untitled)')}`);
                this.write(`      ${paint(row.url, colors.dim)}`);
            });
            this.write(paint('Tip: open <one of the URLs above>', colors.dim));
            this.write(rule());
        } catch (error) {
            this.write(`${paint('✕', colors.red, colors.bold)} Could not search the cache: ${(error as Error).message}`);
        }
    }

    private view(url: string): void {
        try {
            const statement = this.getDb().prepare(
                'SELECT url, title, content, status_code FROM pages WHERE url = ?'
            );
            const page = statement.get(url) as {
                url: string;
                title: string | null;
                content: string | null;
                status_code: number | null;
            } | undefined;
            if (!page) {
                this.write(`${paint('○', colors.yellow)} Page not found in the local cache.`);
                return;
            }

            const content = page.content || '(empty page content)';
            this.write([
                `${paint('PAGE PREVIEW', colors.bold, colors.cyan)}  ${paint(String(page.status_code ?? 'unknown'), colors.dim)}`,
                paint(normalizeTerminalText(page.title || '(untitled)'), colors.bold),
                paint(page.url, colors.dim),
                rule(),
                content.slice(0, 1000),
                content.length > 1000 ? paint('… preview truncated', colors.dim) : '',
                rule(),
            ].filter(Boolean).join('\n'));
        } catch (error) {
            this.write(`${paint('✕', colors.red, colors.bold)} Could not open the page: ${(error as Error).message}`);
        }
    }

    private saveNote(content: string): void {
        const entry: MessageEntry = {
            id: `msg-${Date.now()}-${randomUUID().slice(0, 8)}`,
            parentId: this.options.tree.getLeaf(),
            type: 'message',
            timestamp: Date.now(),
            checksum: '',
            role: 'user',
            content,
        };
        const saved = this.options.tree.appendMessage(entry);
        this.write(`${paint('✓', colors.green, colors.bold)} Note saved ${paint(saved.id, colors.dim)}`);
    }

    private fork(nodeId: string): void {
        try {
            const leaf = this.options.tree.fork(nodeId);
            this.write(`${paint('✓', colors.green, colors.bold)} New branch created at ${paint(leaf, colors.dim)}`);
            this.write(paint('The original path is unchanged. Use tree to inspect both paths.', colors.dim));
        } catch (error) {
            this.write(`${paint('✕', colors.red, colors.bold)} Could not branch: ${(error as Error).message}`);
        }
    }

    private showTree(): void {
        this.write([
            paint('RESEARCH TREE', colors.bold, colors.cyan),
            renderTree(this.options.tree.getAllEntries(), this.options.tree.getLeaf()),
            rule(),
        ].join('\n'));
    }

    private showStatus(): void {
        const entries = this.options.tree.getAllEntries();
        this.write([
            paint('SESSION STATUS', colors.bold, colors.cyan),
            `Entries   ${entries.size}`,
            `Leaf      ${this.options.tree.getLeaf() || '(none yet)'}`,
            `Session   ${this.options.tree.getSessionPath()}`,
            `Database  ${this.dbPath}`,
            rule(),
        ].join('\n'));
    }

    private getDb(): DatabaseSync {
        if (!this.db) {
            this.db = new DatabaseSync(this.dbPath);
        }
        return this.db;
    }

    private closeDb(): void {
        if (this.db) {
            this.db.close();
            this.db = null;
        }
    }

    private getRequestedDbPath(options: string[]): string {
        const optionIndex = options.findIndex((option) => option === '--db-path');
        const equalsOption = options.find((option) => option.startsWith('--db-path='));
        const requested = optionIndex >= 0 ? options[optionIndex + 1] : equalsOption?.slice('--db-path='.length);
        if (!requested) return this.dbPath;
        return isAbsolute(requested) ? requested : join(this.options.projectRoot, requested);
    }
}
