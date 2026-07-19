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
cd api-base
chmod +x setup.sh run.sh
./setup.sh
```

`setup.sh` installs the browser server and the optional desktop GUI. To install them manually:

```bash
python -m pip install -e .          # browser server only
python -m pip install -e ".[gui]"  # browser server and desktop GUI
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

## Docker deployment

This runs the browser server directly. It does not build or run the desktop GUI.

Create a stable session secret in the gitignored `.env` file before starting:

```bash
cp .env.example .env
python -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Replace the placeholder in `.env` with the generated value, then restrict access to it:

```bash
chmod 600 .env
docker compose up -d --build
```

Open <http://127.0.0.1:8765>. Check service status or follow logs with:

```bash
docker compose ps
docker compose logs -f api-base
```

Compose stores the database at `/data/vault.sqlite3` in the named Docker volume `api_base_data`. The database is not copied into the image. Image rebuilds, container restarts, container replacement, and these commands preserve it:

```bash
docker compose down
docker compose up -d
```

Do not run `docker compose down -v` unless you intend to permanently delete the vault volume and every key it contains.

To back up the named volume, stop the service first and copy its SQLite file to a protected host directory:

```bash
docker compose stop api-base
mkdir -p backups
chmod 700 backups
docker compose cp api-base:/data/vault.sqlite3 backups/vault.sqlite3
docker compose start api-base
```

Treat the backup as sensitive encrypted data and retain the master password separately. To restore it, stop the service, run `docker compose cp backups/vault.sqlite3 api-base:/data/vault.sqlite3`, and start the service again.

`API_BASE_SESSION_SECRET` signs browser sessions; it is not the master password and cannot decrypt the vault. Keep it stable across restarts. The master password remains browser-entered and is never persisted by the app. Restarting or recreating the container clears the in-memory decryption material, so the vault returns to the locked state while its database remains intact.

Run only one API Base container. SQLite is local storage and the unlocked key material belongs to one process. The Compose port mapping intentionally listens only on host address `127.0.0.1`; changing it to `8765:8765` exposes the service on other host interfaces and changes its security model.

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
API_BASE_HOST=127.0.0.1
API_BASE_PORT=8765
API_BASE_DATABASE=/absolute/path/to/vault.sqlite3
API_BASE_SESSION_SECRET=a-long-random-session-secret
```

The server binds to `127.0.0.1` by default. Docker overrides the internal bind address to `0.0.0.0` so bridge networking works, while Compose restricts the published host port to `127.0.0.1`. API Base is intentionally not a public network or multi-user service.

## Security notes

- Key ciphertext uses authenticated encryption.
- The database stores a keyed fingerprint for secret-value deduplication, not plaintext keys.
- The master password and decrypted secrets are never written to disk by the app.
- Revealing or copying a key necessarily decrypts it briefly in the running process/browser.
- Plaintext JSON export necessarily contains all readable secrets.
- Do not reverse-proxy or expose this app to a public network without a separate security design.
