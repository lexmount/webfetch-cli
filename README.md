# webfetch-cli

Standalone CLI for Lexmount WebFetch. It does not depend on the Lexmount SDK; it calls the public WebFetch HTTP API with local `x-project-id` and `x-api-key` credentials.

## Install

```bash
uv tool install --force git+https://github.com/lexmount/webfetch-cli.git
```

## Connect

```bash
webfetch-cli auth login --open --connect-base-url https://browser.lexmount.cn
webfetch-cli doctor --json
```

## Use

```bash
webfetch-cli extract --url https://www.bilibili.com
webfetch-cli dump-dom --url https://www.bilibili.com
```
