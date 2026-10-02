---
name: crawl4ai
description: Use the Crawl4AI MCP server to scrape web pages, extract content as clean markdown, or deep-crawl entire sites. Trigger this skill whenever the user wants to fetch a webpage, extract content from a URL, scrape a site, turn a webpage into readable text/markdown, or crawl multiple pages. Even if the user says something like "get me that article", "pull the content from this link", "download this page", "what does this website say", or "crawl this site" — this skill applies. Always use it before trying to fetch URLs manually.
---

## What Crawl4AI does

Crawl4AI is connected as an MCP server. It renders JavaScript-heavy pages using a real browser (Chromium), extracts clean content, and returns it as markdown, HTML, or plain text — ready for you to read and work with.

## Available tools

**`scrape`** — Fetch one page (or a batch of pages). Use this for most cases: reading an article, getting a product page, extracting text from any URL.

**`crawl`** — Like scrape, but with traversal: follow links and discover pages recursively (BFS or DFS). Use this when the user wants to crawl a whole site or follow links from a starting point.

**`close_session`** — End a stateful browser session when you're done with a multi-step crawl workflow.

**`get_artifact`** — Retrieve content from a previous scrape/crawl that used `capture_artifacts`.

## When to use which tool

| User want | Tool |
|---|---|
| Get content from one URL | `scrape` |
| Get content from several URLs at once | `scrape` with a list |
| Follow links, explore a site | `crawl` with deep traversal |
| Crawl a known list of pages | `crawl` with list traversal |

## Common usage patterns

### Scrape a single page (most common)
Call `scrape` with just the URL. The default output is markdown — clean, LLM-ready:
```
targets: "https://example.com/article"
```

### Scrape several pages at once
Pass a list:
```
targets: ["https://site.com/page1", "https://site.com/page2"]
```

### Deep-crawl a site from a seed URL
Use `crawl` with traversal options in `options.traversal`:
```
targets: "https://docs.example.com"
options: { "traversal": { "type": "deep", "strategy": "bfs", "max_pages": 20 } }
```

### Get plain text instead of markdown
Pass a conversion option:
```
options: { "conversion": { "format": "text" } }
```

## Output format

Results come back as a JSON envelope. The content you want is in the `markdown` (or `html`/`text`) field of each result. When presenting content to the user, extract and display the relevant text — don't dump the raw JSON unless they ask for it.

## Tips

- Pages with JavaScript-heavy content (SPAs, dashboards) work fine — Crawl4AI uses a real browser.
- If a page requires login or has anti-bot protection, the scrape may return limited content. Tell the user.
- For very large sites, use `max_pages` to stay within reasonable limits.
- The MCP server needs to be running — it starts automatically via Codex's MCP config.
