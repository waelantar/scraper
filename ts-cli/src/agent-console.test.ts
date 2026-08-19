import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { parseAgentCommand, renderBanner } from './agent-console.js';

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
