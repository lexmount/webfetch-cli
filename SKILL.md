---
name: lexmount-webfetch
description: Use Lexmount WebFetch through webfetch-cli for lightweight public page extraction and DOM dump tasks. Prefer this skill when the task needs structured extraction or rendered HTML capture without creating a live remote browser session.
---

# Lexmount WebFetch CLI

Use `webfetch-cli` when a task needs to fetch a public page through Lexmount WebFetch instead of opening a live browser session.

## Fast Path

Do not run setup checks before every extraction. For ordinary fetch tasks, call the target command directly:

```bash
webfetch-cli extract --url <url>
webfetch-cli dump-dom --url <url>
```

Run checks only when they change the next action:

- First use in a new environment: `webfetch-cli --version` and `webfetch-cli auth status`.
- Missing credentials: `webfetch-cli auth login --open --connect-base-url https://browser.lexmount.cn`, then `webfetch-cli doctor --json`.
- Unexpected command/API failure: `webfetch-cli doctor --json`.
- Unsure installed capability or output shape: `webfetch-cli capabilities --json`.
- Skill file missing or stale: `webfetch-cli skill status`, then `webfetch-cli skill install --force` only if needed.

Do not ask users to paste API keys into chat. `webfetch-cli auth login` stores credentials locally after a one-time PKCE callback.

## Commands

- `webfetch-cli extract --url <url>` extracts structured page content.
- `webfetch-cli extract --dom-id <dom_id>` extracts from an existing DOM dump.
- `webfetch-cli dump-dom --url <url>` captures rendered DOM and returns a reusable `dom_id` when available.

Default output is Markdown optimized for agents. It includes metadata, content,
and extraction/dump quality warnings while hiding trace/debug/raw response
fields.

Use output formats deliberately:

- `--format md`: default agent-readable Markdown.
- `--format text`: plain text plus minimal metadata.
- `--format json`: compact structured output without trace/debug fields.
- `--format json-full`: original API response for debugging.

Use heavy debug fields only when needed:

```bash
webfetch-cli extract --url https://example.com --include-trace --format json-full
webfetch-cli extract --url https://example.com --include-raw-dom --format json-full
```

DOM dump supports engine and cleanup hints:

```bash
webfetch-cli dump-dom --url https://example.com --engine lightmount_dcl
webfetch-cli dump-dom --url https://example.com --filter-scripts-styles
```

Use `--timeout-ms` only when the default request timeout is insufficient.
