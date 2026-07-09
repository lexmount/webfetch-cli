# Lexmount WebFetch CLI

Use `webfetch-cli` when a task needs to fetch a public page through Lexmount WebFetch instead of opening a live browser session.

## Setup

1. Check the CLI:
   ```bash
   webfetch-cli --version
   webfetch-cli skill status
   ```
2. If the skill is missing:
   ```bash
   webfetch-cli skill install --force
   ```
3. Check credentials:
   ```bash
   webfetch-cli auth status
   ```
4. If credentials are missing:
   ```bash
   webfetch-cli auth login --open --connect-base-url https://browser.lexmount.cn
   webfetch-cli doctor --json
   ```

Do not ask users to paste API keys into chat. `webfetch-cli auth login` stores credentials locally after a one-time PKCE callback.

## Commands

- `webfetch-cli extract --url <url>` extracts structured page content.
- `webfetch-cli extract --dom-id <dom_id>` extracts from an existing DOM dump.
- `webfetch-cli dump-dom --url <url>` captures rendered DOM and returns a reusable `dom_id` when available.

Use `--timeout-ms` only when the default request timeout is insufficient.
