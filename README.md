# API Base

A small localhost-only web app for maintaining an encrypted inventory of API keys.

## Features

- Providers: DeepSeek, OpenAI, Anthropic, Gemini, and xAI
- Duplicate display names are allowed
- Duplicate API-key values are rejected and skipped during import
- API keys are encrypted at rest in SQLite with a master-password-derived key
- Add, edit, delete, reveal, and copy keys from the browser
- Refresh one key or all keys against each provider's model-list API
- Store the latest HTTP status and discovered models
- Sort by provider or status and filter by model
- Import wrapped `{"data": [...]}` JSON or a bare JSON array
- Export plaintext JSON or download the encrypted SQLite database
- Localhost-only Waitress server with CSRF protection and no-store security headers

## Install

```bash
git clone https://github.com/norenaboi/api-base
cd /api-base
chmod +x setup.sh run.sh
./setup.sh
```

## Run

```bash
./run.sh
```

Then open:

```text
http://127.0.0.1:8765
```

The launcher stores the database at:

```text
/path/to/api-base/data/vault.sqlite3
```

Stop the app with `Ctrl+C` in the terminal where it is running.

## First launch

1. Create a master password of at least 10 characters.
2. Store the password somewhere safe. It is never saved and cannot be recovered.
3. Add keys manually or use **Import JSON**.

The derived encryption material stays only in the running process. Use **Lock vault** when you are finished. Restarting the app always returns it to a locked state.

## JSON format

The preferred format is:

```json
{
  "data": [
    {
      "name": "Personal",
      "typeofkey": "openai",
      "key": "your-api-key",
      "status_code": 200,
      "models": ["gpt-example"],
      "user_comment": "Used for local development"
    }
  ]
}
```

A bare list containing the same record objects is also accepted.

Rules:

- `name` may be repeated.
- `typeofkey` must be `deepseek`, `openai`, `anthropic`, `gemini`, or `xai`.
- `key` is required and is the deduplication identity.
- `status_code` may be an integer or `null`.
- `models` may be a JSON list or a comma-separated string.
- `user_comment` may be empty.

Import results report imported, duplicate, and invalid-row counts. Import errors never repeat the submitted key value.

## Export and backup

### Export JSON

**Export JSON** produces a portable file in the same `{"data": [...]}` structure. It contains readable API keys. Treat it like a password file and delete it securely when it is no longer needed.

### Encrypted backup

**Encrypted backup** downloads the SQLite database. API-key values remain encrypted in that file. Keep the master password with your backup strategy; the database cannot be unlocked without it.

To restore a backup while API Base is stopped:

```bash
cp /path/to/api-base-vault.sqlite3 /path/to/api-base/data/vault.sqlite3
```

## Provider refresh behavior

Refresh calls the provider's model-list endpoint using the selected key. The app stores:

- the HTTP response status (`200`, `401`, `402`, `429`, and so on)
- model identifiers returned by the provider
- the last-check timestamp

Transport and provider errors are shown without logging or displaying the API key.

## Configuration

Optional environment variables:

```bash
API_BASE_PORT=8765
API_BASE_DATABASE=/absolute/path/to/vault.sqlite3
API_BASE_SESSION_SECRET=a-long-random-session-secret
```

The server always binds to `127.0.0.1`. It is intentionally not a network or multi-user service.

## Security notes

- Key ciphertext uses authenticated encryption.
- The database stores a keyed fingerprint for secret-value deduplication, not plaintext keys.
- The master password and decrypted secrets are never written to disk by the app.
- Revealing or copying a key necessarily decrypts it briefly in the running process/browser.
- Plaintext JSON export necessarily contains all readable secrets.
- Do not reverse-proxy or expose this app to a public network without a separate security design.
