import { after, before, describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

function sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

describe('Agent terminal integration', () => {
    let tempDir: string;

    before(async () => {
        tempDir = await mkdtemp(join(tmpdir(), 'agent-terminal-test-'));
    });

    after(async () => {
        await rm(tempDir, { recursive: true, force: true });
    });

    it('renders the shell and runs a scripted note workflow', async () => {
        const child = spawn('node', [join(__dirname, '..', 'dist', 'agent.js')], {
            cwd: join(__dirname, '..'),
            env: {
                ...process.env,
                SESSION_PATH: join(tempDir, 'session.jsonl'),
                DB_PATH: join(tempDir, 'pages.db'),
            },
            stdio: ['pipe', 'pipe', 'pipe'],
        });

        const stdout: string[] = [];
        const stderr: string[] = [];
        child.stdout.on('data', (data) => stdout.push(data.toString()));
        child.stderr.on('data', (data) => stderr.push(data.toString()));

        const closed = new Promise<number>((resolve) => child.once('close', (code) => resolve(code ?? 1)));

        child.stdin.write('help\n');
        await sleep(100);
        child.stdin.write('A branchable research note.\n');
        await sleep(100);
        child.stdin.write('tree\n');
        await sleep(100);
        child.stdin.write('exit\n');
        assert.equal(await closed, 0);

        const output = stdout.join('');
        assert.match(output, /████/);
        assert.match(output, /AVAILABLE ACTIONS/);
        assert.match(output, /Note saved/);
        assert.match(output, /RESEARCH TREE/);
        assert.match(output, /Session saved\. Goodbye\./);

        const stderrText = stderr.join('');
        if (stderrText && !stderrText.includes('ExperimentalWarning')) {
            assert.fail(`Unexpected stderr: ${stderrText}`);
        }
    });
});
