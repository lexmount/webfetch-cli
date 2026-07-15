# webfetch-cli

Standalone CLI for Lexmount WebFetch. It does not depend on the Lexmount SDK; it calls the public WebFetch HTTP API with local `x-project-id` and `x-api-key` credentials.

## Install

```bash
uv tool install --force git+https://github.com/lexmount/webfetch-cli.git
```

## Connect

Fast path for agents: do not run setup checks before every extraction. Use the target command directly when credentials are already configured.

```bash
webfetch-cli extract --url https://www.bilibili.com
webfetch-cli dump-dom --url https://www.bilibili.com
```

Run setup checks only when needed:

```bash
webfetch-cli auth status
webfetch-cli auth login --open --connect-base-url https://browser.lexmount.cn
webfetch-cli doctor --json
webfetch-cli capabilities --json
```

## Use

```bash
webfetch-cli extract --url https://www.bilibili.com
webfetch-cli dump-dom --url https://www.bilibili.com
```

By default, `extract` and `dump-dom` print Markdown optimized for agents:

- readable metadata and content
- extraction/dump quality warnings
- no trace/debug/raw response fields unless explicitly requested

Use `--format` when you need another shape:

```bash
webfetch-cli extract --url https://www.bilibili.com --format md
webfetch-cli extract --url https://www.bilibili.com --format text
webfetch-cli extract --url https://www.bilibili.com --format json
webfetch-cli extract --url https://www.bilibili.com --format json-full
```

`json-full` preserves the original API response. Use it for debugging or when you
explicitly request heavy fields:

```bash
webfetch-cli extract --url https://example.com --include-trace --format json-full
webfetch-cli extract --url https://example.com --include-raw-dom --format json-full
```

DOM dump supports engine hints and script/style filtering:

```bash
webfetch-cli dump-dom --url https://example.com --engine lightmount_dcl
webfetch-cli dump-dom --url https://example.com --filter-scripts-styles
```
