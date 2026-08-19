import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { AgentConsole } from './agent-console.js';
import { JsonlStorage } from './storage.js';
import { TreeEngine } from './tree.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const projectRoot = join(__dirname, '..', '..');

const sessionPath = process.env.SESSION_PATH || join(projectRoot, 'data', 'session.jsonl');
const dbPath = process.env.DB_PATH || join(projectRoot, 'data', 'pages.db');

const storage = new JsonlStorage(sessionPath);
const tree = new TreeEngine(storage);
tree.load();

const terminal = new AgentConsole({
    tree,
    dbPath,
    projectRoot,
});

await terminal.run();
