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

Use this for normal structured extraction. The CLI sends:

```json
{"extract":{"url":"https://example.com"}}
```

## Dump DOM

```bash
webfetch-cli dump-dom --url https://example.com
```

Use this when extraction needs rendered HTML or a reusable DOM snapshot. The CLI sends:

```json
{"url":"https://example.com"}
```
