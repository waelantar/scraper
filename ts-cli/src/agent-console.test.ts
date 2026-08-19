import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { describeCrawlerRun, normalizeTerminalText, parseAgentCommand, parseCrawlerStats, renderBanner } from './agent-console.js';

describe('AgentConsole command parser', () => {
    it('routes crawler work to the Python-facing command', () => {
        assert.deepEqual(
            parseAgentCommand('crawl https://books.toscrape.com/ --max-depth 1 --max-urls 20'),
            {
                kind: 'crawl',
                seed: 'https://books.toscrape.com/',
                options: ['--max-depth', '1', '--max-urls', '20'],
            }
        );
    });

    it('supports readable commands and legacy slash aliases', () => {
        assert.deepEqual(parseAgentCommand('search python'), { kind: 'query', search: 'python' });
        assert.deepEqual(parseAgentCommand('/query python'), { kind: 'query', search: 'python' });
        assert.deepEqual(parseAgentCommand('open https://example.com'), { kind: 'view', url: 'https://example.com' });
        assert.deepEqual(parseAgentCommand('/fork msg-123'), { kind: 'fork', nodeId: 'msg-123' });
    });

    it('treats plain input as a durable research note', () => {
        assert.deepEqual(
            parseAgentCommand('The search results need a second look.'),
            { kind: 'note', content: 'The search results need a second look.' }
        );
    });

    it('gives actionable feedback for incomplete crawler commands', () => {
        assert.deepEqual(
            parseAgentCommand('crawl'),
            { kind: 'invalid', message: 'Usage: crawl <https://site.example> [crawler options]' }
        );
    });
});

describe('AgentConsole banner', () => {
    it('identifies the product and the supported workflow', () => {
        const banner = renderBanner();
        assert.match(banner, /████/);
        assert.match(banner, /crawl, search, investigate, branch/);
    });
});

describe('Terminal display text', () => {
    it('collapses source HTML title whitespace into one result row', () => {
        assert.equal(normalizeTerminalText('Travel | \n     Books to Scrape - Sandbox'), 'Travel | Books to Scrape - Sandbox');
    });
});

describe('Crawler terminal outcome', () => {
    const stats = JSON.stringify({
        attempted: 1,
        crawled: 0,
        errors: 1,
        skipped_robots: 0,
        visited: 1,
        queue_size: 0,
        active_tasks: 0,
    }, null, 2);

    it('reads the Python crawler statistics from mixed log output', () => {
        assert.deepEqual(parseCrawlerStats(`All tasks complete\n${stats}\nCrawler shut down.`), {
            attempted: 1,
            crawled: 0,
            errors: 1,
            skipped_robots: 0,
        });
    });

    it('reports fetch errors even when the crawler process exits normally', () => {
        assert.deepEqual(describeCrawlerRun(0, stats), {
            state: 'partial',
            result: 'Crawler completed with 1 fetch error and 0 new pages.',
            guidance: 'Open the seed URL to inspect the cached response and status code.',
        });
    });

    it('explains a no-op cache hit instead of presenting it as a fresh crawl', () => {
        const cached = JSON.stringify({ attempted: 1, crawled: 0, errors: 0, skipped_robots: 0 });
        assert.deepEqual(describeCrawlerRun(0, cached), {
            state: 'cached',
            result: 'Crawler finished — no new pages were fetched.',
            guidance: 'The seed may already be cached; use a new --db-path to crawl it again.',
        });
    });
});
