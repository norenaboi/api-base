from __future__ import annotations

from typing import Any

from api_base.vault import Vault, VaultKeyMaterial

SUPPORTED_KEY_TYPES = frozenset(
    {
        "deepseek",
        "openai",
        "anthropic",
        "gemini",
        "xai",
        "huggingface",
        "groq",
        "openrouter",
        "zhipu",
        "moonshot",
    }
)


class DataFormatError(ValueError):
    """Raised when an import payload has an unsupported top-level shape."""


def _normalize_models(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw_models = value.replace("\n", ",").split(",")
    elif isinstance(value, list) and all(isinstance(item, str) for item in value):
        raw_models = value
    else:
        raise ValueError("models must be a list of strings or comma-separated text")
    return list(dict.fromkeys(model.strip() for model in raw_models if model.strip()))


def normalize_record(raw_record: object) -> dict[str, Any]:
    if not isinstance(raw_record, dict):
        raise ValueError("each data item must be an object")

    name = raw_record.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("name must be a non-empty string")

    key_type = raw_record.get("typeofkey")
    if not isinstance(key_type, str) or key_type.lower() not in SUPPORTED_KEY_TYPES:
        raise ValueError(
            "typeofkey must be deepseek, openai, anthropic, gemini, xai, huggingface, "
            "groq, openrouter, zhipu, or moonshot"
        )

    api_key = raw_record.get("key")
    if not isinstance(api_key, str) or not api_key.strip():
        raise ValueError("key must be a non-empty string")

    status_code = raw_record.get("status_code")
    if status_code is not None and (
        isinstance(status_code, bool)
        or not isinstance(status_code, int)
        or not 100 <= status_code <= 599
    ):
        raise ValueError("status_code must be null or an integer from 100 through 599")

    user_comment = raw_record.get("user_comment", "")
    if not isinstance(user_comment, str):
        raise ValueError("user_comment must be a string")

    check_model = raw_record.get("check_model")
    if check_model is not None:
        if not isinstance(check_model, str):
            raise ValueError("check_model must be a string or null")
        check_model = check_model.strip() or None

    openrouter_tier = raw_record.get("openrouter_tier")
    if openrouter_tier not in {None, "free", "paid"}:
        raise ValueError("openrouter_tier must be free, paid, or null")
    if key_type.lower() != "openrouter":
        openrouter_tier = None

    return {
        "name": name.strip(),
        "key_type": key_type.lower(),
        "api_key": api_key.strip(),
        "status_code": status_code,
        "models": _normalize_models(raw_record.get("models", [])),
        "user_comment": user_comment,
        "check_model": check_model,
        "openrouter_tier": openrouter_tier,
    }


def _extract_records(payload: object) -> list[object]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        return payload["data"]
    raise DataFormatError('JSON must be an array or an object containing a "data" array.')


def import_json_data(vault: Vault, keys: VaultKeyMaterial, payload: object) -> dict[str, object]:
    records = _extract_records(payload)
    valid_records: list[dict[str, Any]] = []
    errors: list[dict[str, object]] = []

    for index, raw_record in enumerate(records):
        try:
            valid_records.append(normalize_record(raw_record))
        except (TypeError, ValueError) as error:
            errors.append({"index": index, "message": str(error)})

    results = vault.create_keys(keys, valid_records)
    imported = sum(record_id is not None for record_id in results)

    return {
        "total": len(records),
        "imported": imported,
        "duplicates_skipped": len(results) - imported,
        "error_count": len(errors),
        "errors": errors,
    }


def export_json_data(vault: Vault, keys: VaultKeyMaterial) -> dict[str, list[dict[str, object]]]:
    exported_records: list[dict[str, object]] = []
    for record in vault.list_keys(include_trashed=True):
        exported_records.append(
            {
                "name": record["name"],
                "typeofkey": record["typeofkey"],
                "key": vault.reveal_key(keys, int(record["id"])),
                "status_code": record["status_code"],
                "models": record["models"],
                "user_comment": record["user_comment"],
                "check_model": record.get("check_model"),
                "openrouter_tier": record.get("openrouter_tier"),
            }
        )
    return {"data": exported_records}
