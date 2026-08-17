// ts-cli/src/repl.test.ts
import { describe, it, before, after } from 'node:test';
import assert from 'node:assert';
import { spawn } from 'node:child_process';
import { mkdtemp, rm, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

function sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

describe('REPL integration', () => {
    let tempDir: string;
    let sessionPath: string;
    let dbPath: string;

    before(async () => {
        tempDir = await mkdtemp(join(tmpdir(), 'repl-test-'));
        sessionPath = join(tempDir, 'session.jsonl');
        dbPath = join(tempDir, 'pages.db');

        const db = new DatabaseSync(dbPath);
        db.exec(`CREATE TABLE pages (
            url TEXT PRIMARY KEY,
            title TEXT,
            content TEXT,
            status_code INTEGER,
            crawled_at INTEGER,
            links_json TEXT
        )`);
        db.exec(`INSERT INTO pages (url, title, content, status_code) VALUES
            ('https://example.com', 'Example', 'Hello world', 200)
        `);
        db.close();
    });

    after(async () => {
        await rm(tempDir, { recursive: true, force: true });
    });

    it('runs scripted session', async () => {
        // Build the CLI first: npm run build
        const cliPath = join(__dirname, '..', 'dist', 'index.js');
        const child = spawn('node', [cliPath], {
            env: {
                ...process.env,
                SESSION_PATH: sessionPath,
                DB_PATH: dbPath,
            },
            stdio: ['pipe', 'pipe', 'pipe'],
            cwd: join(__dirname, '..'),
        });

        const stdout: string[] = [];
        const stderr: string[] = [];

        child.stdout.on('data', (data) => stdout.push(data.toString()));
        child.stderr.on('data', (data) => stderr.push(data.toString()));

        // Attach close listener immediately
        const closed = new Promise<void>((resolve) => {
            child.once('close', () => resolve());
        });

        // 1. Append a message
        child.stdin.write('Hello world\n');
        await sleep(200);

        // 2. Get the message ID from the session file
        const content = await readFile(sessionPath, 'utf-8');
        const lines = content.split('\n').filter(Boolean);
        const firstEntry = JSON.parse(lines[0]);
        const msgId = firstEntry.id;

        // 3. Fork from that message
        child.stdin.write(`/fork ${msgId}\n`);
        await sleep(200);

        // 4. Query the DB
        child.stdin.write('/query hello\n');
        await sleep(200);

        // 5. Show tree
        child.stdin.write('/tree\n');
        await sleep(200);

        // 6. Show status
        child.stdin.write('/status\n');
        await sleep(200);

        // 7. Exit
        child.stdin.write('/exit\n');
        await sleep(200);

        await closed;

        const output = stdout.join('');
        // Check message appended
        assert.ok(output.includes('Hello world'));
        // Check fork success
        assert.ok(output.includes('Forked'));
        // Check query found results
        assert.ok(output.includes('Found 1 pages'));
        // Check /tree rendered the message
        assert.ok(output.includes('user: Hello world'));
        // Check status shows session path
        assert.ok(output.includes('Session:'));
        // Allow SQLite experimental warning in stderr
        const stderrStr = stderr.join('');
        if (stderrStr && !stderrStr.includes('ExperimentalWarning')) {
            assert.fail(`Unexpected stderr: ${stderrStr}`);
        }
    });
});