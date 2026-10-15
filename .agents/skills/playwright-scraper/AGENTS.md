# Web Scraping with Playwright MCP

When the user asks you to fetch a webpage, extract content from a URL, read an article, scrape a site, or do anything involving opening a URL — use the Playwright MCP browser tools listed below. Do not use `curl`, `fetch`, or raw HTTP requests for this; Playwright renders full JavaScript and handles dynamic pages correctly.

## Available tools

These tools are provided by the `@playwright/mcp` MCP server:

- `browser_navigate` — Open a URL
- `browser_snapshot` — Get the structured accessibility tree of the current page (good for finding elements and reading hierarchical content)
- `browser_evaluate` — Run JavaScript in the page (best for extracting raw text or data)
- `browser_wait_for` — Wait for a selector or time delay before extracting
- `browser_take_screenshot` — Capture a screenshot
- `browser_click` — Click a button, link, or element
- `browser_type` — Type into an input field
- `browser_press_key` — Send a keystroke (Enter, Escape, etc.)
- `browser_select_option` — Choose from a dropdown
- `browser_close` — Close the browser when done

## How to scrape a page

### Read an article or documentation page

1. `browser_navigate` to the URL
2. `browser_evaluate` with this expression to extract the main content:
   ```js
   const el = document.querySelector('article') 
     || document.querySelector('main') 
     || document.querySelector('[role="main"]') 
     || document.body;
   return el.innerText;
   ```
3. Present the extracted text to the user, cleaned up — do not dump raw HTML.

### JavaScript-heavy pages (SPAs, dashboards)

1. `browser_navigate` to the URL
2. `browser_wait_for` — wait for a known element selector, or use `time: 2000` (2 second delay)
3. Then extract with `browser_evaluate`

### Get structured content (headings, lists)

Use `browser_snapshot` after navigating — it preserves heading hierarchy and list structure better than `innerText`.

### Extract a table as data

Use `browser_evaluate` with:
```js
const rows = Array.from(document.querySelectorAll('table tr'));
return rows.map(row =>
  Array.from(row.querySelectorAll('th, td')).map(cell => cell.innerText.trim())
);
```

### Paginated content

1. Navigate and extract page 1
2. Use `browser_snapshot` to locate the "Next page" element
3. `browser_click` it, then `browser_wait_for` new content
4. Extract again — repeat until no next button or limit reached

### Multiple URLs

Navigate to each URL in sequence; there is no batch mode.

## Output format

- Articles/docs: extract and present the main text, stripped of navigation and footer noise.
- Structured data: format as a markdown table or bulleted list.
- Screenshots: show inline and describe the content.
- Do not dump raw HTML or the full accessibility tree unless the user explicitly asks.

## Tips

- Playwright renders JavaScript, so SPAs and lazy-loaded content work fine.
- For login-gated pages: use `browser_type` and `browser_click` to fill the login form first, then navigate to the target in the same session.
- If the page returns a Cloudflare or CAPTCHA challenge, tell the user — there is no automatic bypass.
- Use targeted selectors (`article`, `main`, `.content`) on large pages instead of `document.body.innerText` to keep the output manageable.
- Call `browser_close` when a multi-step session is finished.

## Setup (one-time)

Install and register the MCP server if not already done:

```bash
npx @playwright/mcp@latest
```

Add to your agent's MCP config:
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
