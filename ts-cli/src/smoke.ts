// src/smoke.ts
import { DatabaseSync } from 'node:sqlite';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import { existsSync } from 'fs';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// Locate database (try common locations)
const possiblePaths = [
    join(__dirname, '..', '..', 'data', 'pages.db'),
    join(__dirname, '..', '..', 'crawler.db'),
    join(__dirname, '..', 'crawler.db'),
];

let dbPath: string | null = null;
for (const p of possiblePaths) {
    if (existsSync(p)) {
        dbPath = p;
        break;
    }
}

if (!dbPath) {
    console.error('❌ No database file found in any of these locations:');
    possiblePaths.forEach(p => console.error(`  - ${p}`));
    console.error('\n💡 Run the Python crawler first to create the database:');
    console.error('   cd .. && python -m python_engine.orchestrator');
    process.exit(1);
}

console.log(`📁 Found database at: ${dbPath}`);

const db = new DatabaseSync(dbPath);

// 1. Check if the pages table exists (don't create it)
const tableCheck = db.prepare(
    "SELECT name FROM sqlite_master WHERE type='table' AND name='pages'"
).get();

if (!tableCheck) {
    console.error('❌ Table "pages" does not exist in the database.');
    console.error('💡 Run the Python crawler to create and populate the table:');
    console.error('   cd .. && python -m python_engine.orchestrator');
    process.exit(1);
}

// 2. Verify the table has the expected columns (schema contract check)
const columnInfo = db.prepare('PRAGMA table_info(pages)').all();
const expectedColumns = ['url', 'title', 'content', 'status_code', 'crawled_at', 'links_json'];
const actualColumns = columnInfo.map((row) => String((row as { name: string }).name));
if (JSON.stringify(actualColumns) !== JSON.stringify(expectedColumns)) {
    console.error('❌ Schema mismatch!');
    console.error('Expected columns:', expectedColumns);
    console.error('Actual columns:', actualColumns);
    console.error('💡 The Python crawler schema has changed. Update the smoke test or re-run the crawler.');
    process.exit(1);
}

// 3. Read rows
const rows = db.prepare('SELECT url, title, status_code FROM pages LIMIT 5').all();
console.log(`✅ Found ${rows.length} pages in the database:`);
console.table(rows);

console.log('✅ Cross-language contract validated: TypeScript can read Python-written SQLite.');