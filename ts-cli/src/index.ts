// ts-cli/src/index.ts
import { JsonlStorage } from './storage.js';
import { TreeEngine } from './tree.js';
import { Repl } from './repl.js';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { dirname } from 'node:path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const sessionPath = process.env.SESSION_PATH ||
    join(__dirname, '..', '..', 'data', 'session.jsonl');

const dbPath = process.env.DB_PATH ||
    join(__dirname, '..', '..', 'data', 'pages.db');

const storage = new JsonlStorage(sessionPath);
const tree = new TreeEngine(storage);
tree.load();

const repl = new Repl(tree, dbPath);
await repl.run();