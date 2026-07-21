from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

CHECK_VALUE = b"api-base-vault-check-v1"
CHECK_AAD = b"api-base:metadata:v1"
KEY_AAD = b"api-base:key:v1"
SALT_BYTES = 16
NONCE_BYTES = 12
MINIMUM_PASSWORD_LENGTH = 10
OPENROUTER_TIER_UNCHANGED = object()


class VaultError(Exception):
    """Base class for expected vault errors."""


class InvalidPasswordError(VaultError):
    """Raised when a master password cannot unlock the vault."""


class VaultAlreadyInitializedError(VaultError):
    """Raised when initialization is attempted twice."""


class VaultNotInitializedError(VaultError):
    """Raised when an uninitialized vault is accessed."""


class PasswordTooShortError(VaultError):
    """Raised when a new master password is too short."""


class KeyNotFoundError(VaultError):
    """Raised when an API-key record does not exist."""


class DuplicateKeyError(VaultError):
    """Raised when the same API-key value already exists."""


@dataclass(frozen=True, slots=True)
class VaultKeyMaterial:
    encryption_key: bytes
    fingerprint_key: bytes


def _derive_keys(password: str, salt: bytes) -> VaultKeyMaterial:
    derived = Scrypt(salt=salt, length=64, n=2**15, r=8, p=1).derive(password.encode("utf-8"))
    return VaultKeyMaterial(encryption_key=derived[:32], fingerprint_key=derived[32:])


class Vault:
    """Encrypted SQLite-backed API-key vault."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self._migrate()

    def _migrate(self) -> None:
        if not self.is_initialized():
            return
        with self._connect() as connection:
            columns = {
                row["name"]
                for row in connection.execute(
                    "SELECT name FROM pragma_table_info('api_keys')"
                ).fetchall()
            }
            if "error_message" not in columns:
                connection.execute(
                    "ALTER TABLE api_keys ADD COLUMN error_message TEXT"
                )
            if "check_model" not in columns:
                connection.execute(
                    "ALTER TABLE api_keys ADD COLUMN check_model TEXT"
                )
            if "trashed" not in columns:
                connection.execute(
                    "ALTER TABLE api_keys ADD COLUMN trashed INTEGER NOT NULL DEFAULT 0"
                )
            if "openrouter_tier" not in columns:
                connection.execute("ALTER TABLE api_keys ADD COLUMN openrouter_tier TEXT")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def is_initialized(self) -> bool:
        if not self.database_path.exists():
            return False
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'vault_metadata'"
                ).fetchone()
                if row is None:
                    return False
                return (
                    connection.execute("SELECT 1 FROM vault_metadata WHERE id = 1").fetchone()
                    is not None
                )
        except sqlite3.DatabaseError:
            return False

    def initialize(self, password: str) -> None:
        if len(password) < MINIMUM_PASSWORD_LENGTH:
            raise PasswordTooShortError(
                f"Master password must contain at least {MINIMUM_PASSWORD_LENGTH} characters."
            )
        if self.is_initialized():
            raise VaultAlreadyInitializedError("The vault has already been initialized.")

        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        salt = os.urandom(SALT_BYTES)
        nonce = os.urandom(NONCE_BYTES)
        keys = _derive_keys(password, salt)
        ciphertext = AESGCM(keys.encryption_key).encrypt(nonce, CHECK_VALUE, CHECK_AAD)

        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE vault_metadata (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    salt BLOB NOT NULL,
                    check_nonce BLOB NOT NULL,
                    check_ciphertext BLOB NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                INSERT INTO vault_metadata (id, salt, check_nonce, check_ciphertext)
                VALUES (1, ?, ?, ?)
                """,
                (salt, nonce, ciphertext),
            )
            connection.execute(
                """
                CREATE TABLE api_keys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    key_type TEXT NOT NULL,
                    key_ciphertext BLOB NOT NULL,
                    key_nonce BLOB NOT NULL,
                    key_fingerprint BLOB NOT NULL UNIQUE,
                    key_first_four TEXT NOT NULL,
                    key_last_four TEXT NOT NULL,
                    status_code INTEGER,
                    error_message TEXT,
                    models_json TEXT NOT NULL DEFAULT '[]',
                    user_comment TEXT NOT NULL DEFAULT '',
                    check_model TEXT,
                    openrouter_tier TEXT,
                    last_checked_at TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    trashed INTEGER NOT NULL DEFAULT 0
                )
                """
            )

    def unlock(self, password: str) -> VaultKeyMaterial:
        if not self.is_initialized():
            raise VaultNotInitializedError("The vault has not been initialized.")

        with self._connect() as connection:
            metadata = connection.execute(
                """
                SELECT salt, check_nonce, check_ciphertext
                FROM vault_metadata
                WHERE id = 1
                """
            ).fetchone()

        keys = _derive_keys(password, metadata["salt"])
        try:
            check_value = AESGCM(keys.encryption_key).decrypt(
                metadata["check_nonce"], metadata["check_ciphertext"], CHECK_AAD
            )
        except InvalidTag as error:
            raise InvalidPasswordError("The master password is incorrect.") from error
        if check_value != CHECK_VALUE:
            raise InvalidPasswordError("The master password is incorrect.")
        self._ensure_key_prefixes(keys)
        return keys

    def _ensure_key_prefixes(self, keys: VaultKeyMaterial) -> None:
        """Add and backfill key previews for vaults created before this field existed."""
        with self._connect() as connection:
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(api_keys)").fetchall()
            }
            if "key_first_four" not in columns:
                connection.execute("ALTER TABLE api_keys ADD COLUMN key_first_four TEXT")

            rows = connection.execute(
                """
                SELECT id, key_nonce, key_ciphertext
                FROM api_keys
                WHERE key_first_four IS NULL
                """
            ).fetchall()
            for row in rows:
                try:
                    plaintext = AESGCM(keys.encryption_key).decrypt(
                        row["key_nonce"], row["key_ciphertext"], KEY_AAD
                    )
                except InvalidTag:
                    continue
                connection.execute(
                    "UPDATE api_keys SET key_first_four = ? WHERE id = ?",
                    (plaintext.decode("utf-8")[:4], row["id"]),
                )

    def _insert_key(
        self,
        connection: sqlite3.Connection,
        cipher: AESGCM,
        keys: VaultKeyMaterial,
        *,
        name: str,
        key_type: str,
        api_key: str,
        status_code: int | None = None,
        models: list[str] | None = None,
        user_comment: str = "",
        check_model: str | None = None,
        openrouter_tier: str | None = None,
    ) -> int:
        normalized_key = api_key.strip()
        nonce = os.urandom(NONCE_BYTES)
        ciphertext = cipher.encrypt(nonce, normalized_key.encode("utf-8"), KEY_AAD)
        fingerprint = hmac.new(
            keys.fingerprint_key, normalized_key.encode("utf-8"), hashlib.sha256
        ).digest()
        serialized_models = json.dumps(models or [], separators=(",", ":"))

        try:
            cursor = connection.execute(
                """
                INSERT INTO api_keys (
                    name, key_type, key_ciphertext, key_nonce, key_fingerprint,
                    key_first_four, key_last_four, status_code, models_json, user_comment,
                    check_model, openrouter_tier
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name,
                    key_type,
                    ciphertext,
                    nonce,
                    fingerprint,
                    normalized_key[:4],
                    normalized_key[-4:],
                    status_code,
                    serialized_models,
                    user_comment,
                    check_model,
                    openrouter_tier if key_type == "openrouter" else None,
                ),
            )
        except sqlite3.IntegrityError as error:
            if "key_fingerprint" in str(error):
                raise DuplicateKeyError("That API key already exists in the vault.") from error
            raise
        return int(cursor.lastrowid)

    def create_key(
        self,
        keys: VaultKeyMaterial,
        *,
        name: str,
        key_type: str,
        api_key: str,
        status_code: int | None = None,
        models: list[str] | None = None,
        user_comment: str = "",
        check_model: str | None = None,
        openrouter_tier: str | None = None,
    ) -> int:
        with self._connect() as connection:
            return self._insert_key(
                connection,
                AESGCM(keys.encryption_key),
                keys,
                name=name,
                key_type=key_type,
                api_key=api_key,
                status_code=status_code,
                models=models,
                user_comment=user_comment,
                check_model=check_model,
                openrouter_tier=openrouter_tier,
            )

    def create_keys(
        self, keys: VaultKeyMaterial, records: list[dict[str, object]]
    ) -> list[int | None]:
        """Insert many key records in one transaction; None marks a skipped duplicate."""
        cipher = AESGCM(keys.encryption_key)
        results: list[int | None] = []
        with self._connect() as connection:
            for record in records:
                try:
                    results.append(self._insert_key(connection, cipher, keys, **record))  # type: ignore[arg-type]
                except DuplicateKeyError:
                    results.append(None)
        return results

    def update_key(
        self,
        keys: VaultKeyMaterial,
        record_id: int,
        *,
        name: str,
        key_type: str,
        api_key: str | None,
        status_code: int | None,
        models: list[str],
        user_comment: str,
        check_model: str | None = ...,  # sentinel: None means "not provided" (keep existing)
    ) -> None:
        assignments = [
            "name = ?",
            "key_type = ?",
            "status_code = ?",
            "models_json = ?",
            "user_comment = ?",
        ]
        if key_type != "openrouter":
            assignments.append("openrouter_tier = NULL")
        parameters: list[object] = [
            name,
            key_type,
            status_code,
            json.dumps(models, separators=(",", ":")),
            user_comment,
        ]

        if api_key is not None:
            normalized_key = api_key.strip()
            nonce = os.urandom(NONCE_BYTES)
            ciphertext = AESGCM(keys.encryption_key).encrypt(
                nonce, normalized_key.encode("utf-8"), KEY_AAD
            )
            fingerprint = hmac.new(
                keys.fingerprint_key, normalized_key.encode("utf-8"), hashlib.sha256
            ).digest()
            assignments.extend(
                [
                    "key_ciphertext = ?",
                    "key_nonce = ?",
                    "key_fingerprint = ?",
                    "key_first_four = ?",
                    "key_last_four = ?",
                ]
            )
            parameters.extend(
                [ciphertext, nonce, fingerprint, normalized_key[:4], normalized_key[-4:]]
            )

        if check_model is not ...:
            assignments.append("check_model = ?")
            parameters.append(check_model if check_model else None)

        assignments.append("updated_at = CURRENT_TIMESTAMP")
        parameters.append(record_id)
        query = f"UPDATE api_keys SET {', '.join(assignments)} WHERE id = ?"  # noqa: S608
        try:
            with self._connect() as connection:
                cursor = connection.execute(query, parameters)
                if cursor.rowcount == 0:
                    raise KeyNotFoundError(f"API-key record {record_id} was not found.")
        except sqlite3.IntegrityError as error:
            if "key_fingerprint" in str(error):
                raise DuplicateKeyError("That API key already exists in the vault.") from error
            raise

    def delete_key(self, record_id: int) -> None:
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM api_keys WHERE id = ?", (record_id,))
            if cursor.rowcount == 0:
                raise KeyNotFoundError(f"API-key record {record_id} was not found.")

    def update_check_result(
        self,
        record_id: int,
        status_code: int | None,
        models: list[str],
        error_message: str | None = None,
        user_comment: str | None = None,  # None means "leave the existing comment"
        openrouter_tier: str | None | object = OPENROUTER_TIER_UNCHANGED,
    ) -> None:
        assignments = [
            "status_code = ?",
            "models_json = ?",
            "error_message = ?",
            "last_checked_at = CURRENT_TIMESTAMP",
            "updated_at = CURRENT_TIMESTAMP",
        ]
        parameters: list[object] = [
            status_code,
            json.dumps(models, separators=(",", ":")),
            error_message,
        ]
        if user_comment is not None:
            assignments.insert(3, "user_comment = ?")
            parameters.append(user_comment)
        if openrouter_tier is not OPENROUTER_TIER_UNCHANGED:
            if openrouter_tier not in {"free", "paid", None}:
                raise ValueError(f"Unsupported OpenRouter tier: {openrouter_tier}")
            assignments.append("openrouter_tier = ?")
            parameters.append(openrouter_tier)
        parameters.append(record_id)
        query = f"UPDATE api_keys SET {', '.join(assignments)} WHERE id = ?"  # noqa: S608
        with self._connect() as connection:
            cursor = connection.execute(query, parameters)
            if cursor.rowcount == 0:
                raise KeyNotFoundError(f"API-key record {record_id} was not found.")

    def set_trashed(self, record_id: int, trashed: bool) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE api_keys SET trashed = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (1 if trashed else 0, record_id),
            )
            if cursor.rowcount == 0:
                raise KeyNotFoundError(f"API-key record {record_id} was not found.")

    @staticmethod
    def _record_from_row(row: sqlite3.Row) -> dict[str, object]:
        return {
            "id": row["id"],
            "name": row["name"],
            "typeofkey": row["key_type"],
            "masked_key": (
                f"{row['key_first_four']}...{row['key_last_four']}"
                if row["key_first_four"]
                else f"••••{row['key_last_four']}"
            ),
            "status_code": row["status_code"],
            "error_message": row["error_message"],
            "check_model": row["check_model"],
            "openrouter_tier": row["openrouter_tier"],
            "models": json.loads(row["models_json"]),
            "user_comment": row["user_comment"],
            "last_checked_at": row["last_checked_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "trashed": bool(row["trashed"]),
        }

    def get_key(self, record_id: int) -> dict[str, object]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, name, key_type, key_first_four, key_last_four, status_code,
                       models_json, user_comment, error_message, check_model, openrouter_tier,
                       last_checked_at, created_at, updated_at, trashed
                FROM api_keys
                WHERE id = ?
                """,
                (record_id,),
            ).fetchone()
        if row is None:
            raise KeyNotFoundError(f"API-key record {record_id} was not found.")
        return self._record_from_row(row)

    def list_models(self) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT CAST(json_each.value AS TEXT) AS model
                FROM api_keys, json_each(api_keys.models_json)
                WHERE api_keys.trashed = 0
                """
            ).fetchall()
        return sorted(row["model"] for row in rows)

    @staticmethod
    def _key_filters(
        *,
        model: str | None,
        key_type: str | None,
        status: str | None,
        status_code: int | None,
        openrouter_tier: str | None,
        include_trashed: bool,
    ) -> tuple[str, list[object]]:
        conditions: list[str] = []
        parameters: list[object] = []
        if not include_trashed:
            conditions.append("api_keys.trashed = 0")
        if model:
            conditions.append(
                "EXISTS (SELECT 1 FROM json_each(api_keys.models_json) "
                "WHERE instr(lower(CAST(value AS TEXT)), lower(?)) > 0)"
            )
            parameters.append(model)
        if key_type:
            conditions.append("api_keys.key_type = ?")
            parameters.append(key_type)
        if status_code is not None:
            conditions.append("api_keys.status_code = ?")
            parameters.append(status_code)
        elif status:
            status_conditions = {
                "ok": "api_keys.status_code BETWEEN 200 AND 299",
                "rate": "api_keys.status_code = 429",
                "error": (
                    "api_keys.status_code IS NOT NULL AND api_keys.status_code != 429 "
                    "AND (api_keys.status_code < 200 OR api_keys.status_code >= 300)"
                ),
                "unchecked": "api_keys.status_code IS NULL",
            }
            if status not in status_conditions:
                raise ValueError(f"Unsupported status filter: {status}")
            conditions.append(status_conditions[status])
        if openrouter_tier:
            if openrouter_tier not in {"free", "paid"}:
                raise ValueError(f"Unsupported OpenRouter tier filter: {openrouter_tier}")
            conditions.extend(
                ["api_keys.key_type = 'openrouter'", "api_keys.openrouter_tier = ?"]
            )
            parameters.append(openrouter_tier)
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        return where_clause, parameters

    def count_keys(
        self,
        *,
        model: str | None = None,
        key_type: str | None = None,
        status: str | None = None,
        status_code: int | None = None,
        openrouter_tier: str | None = None,
        include_trashed: bool = False,
    ) -> int:
        where_clause, parameters = self._key_filters(
            model=model,
            key_type=key_type,
            status=status,
            status_code=status_code,
            openrouter_tier=openrouter_tier,
            include_trashed=include_trashed,
        )
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT COUNT(*) AS count FROM api_keys {where_clause}",  # noqa: S608
                parameters,
            ).fetchone()
        return int(row["count"])

    def list_keys(
        self,
        *,
        sort_by: str = "id",
        direction: str = "asc",
        model: str | None = None,
        key_type: str | None = None,
        status: str | None = None,
        status_code: int | None = None,
        openrouter_tier: str | None = None,
        include_trashed: bool = False,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, object]]:
        sort_columns = {
            "id": "api_keys.id",
            "name": "api_keys.name COLLATE NOCASE",
            "typeofkey": "api_keys.key_type COLLATE NOCASE",
            "status_code": "api_keys.status_code",
            "updated_at": "api_keys.updated_at",
        }
        if sort_by not in sort_columns:
            raise ValueError(f"Unsupported sort column: {sort_by}")
        normalized_direction = direction.lower()
        if normalized_direction not in {"asc", "desc"}:
            raise ValueError(f"Unsupported sort direction: {direction}")
        if limit is not None and limit < 1:
            raise ValueError("Limit must be positive.")
        if offset < 0:
            raise ValueError("Offset cannot be negative.")

        where_clause, parameters = self._key_filters(
            model=model,
            key_type=key_type,
            status=status,
            status_code=status_code,
            openrouter_tier=openrouter_tier,
            include_trashed=include_trashed,
        )
        sort_column = sort_columns[sort_by]
        nulls_last = (
            "(api_keys.status_code IS NULL) ASC, " if sort_by == "status_code" else ""
        )
        pagination = ""
        if limit is not None:
            pagination = "LIMIT ? OFFSET ?"
            parameters.extend((limit, offset))
        query = (
            f"""
            SELECT id, name, key_type, key_first_four, key_last_four, status_code, models_json,
                   user_comment, error_message, check_model, openrouter_tier, last_checked_at,
                   created_at, updated_at, trashed
            FROM api_keys
            {where_clause}
            ORDER BY {nulls_last}{sort_column} {normalized_direction.upper()}, api_keys.id ASC
            {pagination}
            """  # noqa: S608
        )

        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()

        return [self._record_from_row(row) for row in rows]

    def reveal_key(self, keys: VaultKeyMaterial, record_id: int) -> str:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT key_nonce, key_ciphertext FROM api_keys WHERE id = ?", (record_id,)
            ).fetchone()
        if row is None:
            raise KeyNotFoundError(f"API-key record {record_id} was not found.")
        plaintext = AESGCM(keys.encryption_key).decrypt(
            row["key_nonce"], row["key_ciphertext"], KEY_AAD
        )
        return plaintext.decode("utf-8")
