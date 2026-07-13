---
name: lexmount-webfetch
description: Use Lexmount WebFetch through webfetch-cli for lightweight public page extraction and DOM dump tasks. Prefer this skill when the task needs structured extraction or rendered HTML capture without creating a live remote browser session.
---

# Lexmount WebFetch CLI

Use `webfetch-cli` for Lexmount WebFetch extraction and DOM dump tasks.

## Required checks

```bash
webfetch-cli --version
webfetch-cli auth status
webfetch-cli capabilities --json
```

If credentials are missing, run:

```bash
webfetch-cli auth login --open --connect-base-url https://browser.lexmount.cn
webfetch-cli doctor --json
```

Never paste API keys into chat.

## Extract

```bash
webfetch-cli extract --url https://example.com
```

Default output is Markdown optimized for agents. It includes page metadata,
extraction quality warnings, and the extracted main text.

Use this for normal structured extraction. The CLI sends:

```json
{"extract":{"url":"https://example.com"}}
```

When debugging, request the full raw API response explicitly:

```bash
webfetch-cli extract --url https://example.com --include-trace --format json-full
webfetch-cli extract --url https://example.com --include-raw-dom --format json-full
```

Use `--format json` for compact structured data and `--format text` for plain text.

## Dump DOM

```bash
webfetch-cli dump-dom --url https://example.com
```

Default output is Markdown with DOM metadata, dump quality warnings, and captured
HTML. Debug fields are hidden unless `--format json-full` is used.

Use this when extraction needs rendered HTML or a reusable DOM snapshot. The CLI sends:

```json
{"url":"https://example.com"}
```

Use optional engine and cleanup hints when needed:

```bash
webfetch-cli dump-dom --url https://example.com --engine lightmount_dcl
webfetch-cli dump-dom --url https://example.com --filter-scripts-styles
```
