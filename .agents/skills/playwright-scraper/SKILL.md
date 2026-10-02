---
name: playwright-scraper
description: Use the Playwright MCP browser to scrape web pages, extract clean text or markdown, and interact with JavaScript-heavy or dynamic sites — without needing any special scraping service. Trigger this skill whenever the user wants to fetch a webpage, extract content from a URL, read an article or documentation page, scrape a site, turn a webpage into readable text, get data from a web page, or open and interact with a URL. Works with any MCP-compatible agent including OpenCode with DeepSeek, Gemini, or other models. Even if the user says "get me that page", "what does this URL say", "pull content from this link", "open this website", "scrape this", or "check this URL" — use this skill. Always prefer this over manually constructing HTTP requests.
---

## What this skill does

Uses the `@playwright/mcp` browser to open real web pages (with full JavaScript rendering), extract content, and return it in a useful format. Works identically across any MCP-capable agent: Codex, OpenCode + DeepSeek, Gemini CLI, etc.

---

## Available tools (from `@playwright/mcp`)

| Tool | Purpose |
|---|---|
| `browser_navigate` | Open a URL in the browser |
| `browser_snapshot` | Get the structured accessibility tree of the current page — best for finding elements and reading structured content |
| `browser_evaluate` | Run JavaScript in the page — best for extracting raw text, innerHTML, or computed data |
| `browser_wait_for` | Wait for a condition, selector, or delay before extracting |
| `browser_take_screenshot` | Capture a screenshot (use when structure or layout matters) |
| `browser_click` | Click a button, link, or element |
| `browser_type` | Type into an input field |
| `browser_press_key` | Send a keystroke (e.g. Enter, Escape) |
| `browser_select_option` | Choose from a `<select>` dropdown |
| `browser_tabs` | List open tabs, useful for multi-page flows |
| `browser_close` | Close the browser when done |

---

## Common patterns

### 1. Read an article or documentation page

```
1. browser_navigate  →  url: "https://example.com/article"
2. browser_evaluate  →  extract readable text:
   expression: "document.body.innerText"
3. Present the extracted text to the user, cleaned up.
```

For even cleaner extraction (removes nav, ads, boilerplate):
```js
// In browser_evaluate:
const article = document.querySelector('article') 
  || document.querySelector('main') 
  || document.querySelector('[role="main"]') 
  || document.body;
return article.innerText;
```

### 2. Get structured content (headings, lists, tables)

Use `browser_snapshot` right after navigating — it returns the accessibility tree, which preserves heading hierarchy and list structure better than raw `innerText`.

### 3. Scrape a JavaScript-heavy page (SPA, dashboard)

```
1. browser_navigate  →  url: "..."
2. browser_wait_for  →  selector: "css=[data-loaded]"  (or a known element)
   OR: time: 2000  (2s delay if no reliable selector)
3. browser_evaluate  →  extract the content you need
```

Playwright renders the full page including JS before you extract, so SPAs, lazy-loaded content, and dynamic tables all work.

### 4. Paginated content (click "Next page")

```
1. browser_navigate  →  url: "..."
2. browser_snapshot  →  find the "Next" button selector
3. Collect content from page 1
4. browser_click  →  selector for "Next"
5. browser_wait_for  →  new content to appear
6. Collect content from page 2
7. Repeat until no "Next" button or limit reached
```

### 5. Extract a table as data

```js
// In browser_evaluate:
const rows = Array.from(document.querySelectorAll('table tr'));
return rows.map(row =>
  Array.from(row.querySelectorAll('th, td')).map(cell => cell.innerText.trim())
);
```

### 6. Scrape multiple URLs

Navigate to each URL in sequence and collect results. There is no batch mode — loop through the list one at a time.

---

## Output format

- For articles/docs: extract and present the main text directly, cleaned of navigation/footer noise.
- For structured data (tables, lists): format as markdown table or bulleted list.
- For screenshots: show the image inline and describe what it contains.
- Don't dump raw HTML or the full accessibility tree unless the user asks for it.

---

## Setup (if not yet configured)

Install the official Playwright MCP server once:
```bash
npx @playwright/mcp@latest
```

Add to your MCP config (Codex `~/.Codex/claude_desktop_config.json`, or OpenCode equivalent):
```json
{
  "mcpServers": {
    "playwright": {
      "command": "npx",
      "args": ["@playwright/mcp@latest"]
    }
  }
}
```

After adding, restart the agent. The `browser_*` tools become available automatically.

---

## Tips

- **JS-heavy pages**: Always prefer Playwright over `fetch`/`curl` — it waits for JavaScript to run.
- **Login-gated pages**: Use `browser_type` + `browser_click` to fill login forms, then navigate to the target page in the same session.
- **Anti-bot protection** (Cloudflare, CAPTCHA): The scrape may return a challenge page. Tell the user — there is no automatic bypass.
- **Large pages**: Use targeted selectors (`article`, `main`, `.content`) instead of `document.body.innerText` to stay within context limits.
- **Always close**: Call `browser_close` when done with a multi-step scraping session to free browser resources.
