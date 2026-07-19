from __future__ import annotations

from collections.abc import Iterable

import httpx

from api_base.providers import ProviderResult, check_key_health, fetch_models
from api_base.vault import KeyNotFoundError, Vault, VaultKeyMaterial


def refresh_key(
    vault: Vault,
    keys: VaultKeyMaterial,
    record_id: int,
    *,
    transport: httpx.BaseTransport | None = None,
) -> ProviderResult:
    record = next((item for item in vault.list_keys() if item["id"] == record_id), None)
    if record is None:
        raise KeyNotFoundError(f"API-key record {record_id} was not found.")

    api_key = vault.reveal_key(keys, record_id)
    provider = str(record["typeofkey"])
    check_model = record.get("check_model") or None

    # 1. Fetch models first — this should work even if the chat-completion
    #    health check would rate-limit or fail, so models are always populated.
    model_result = fetch_models(provider, api_key, transport=transport)
    models = model_result.models if model_result.status_code == 200 else []

    # 2. Chat-completion health check — the status code displayed comes from this.
    health = check_key_health(provider, api_key, model=check_model, transport=transport)

    # 3. Persist: models from the fetch, status+error from the health check.
    combined_error = health.error or model_result.error
    vault.update_check_result(
        record_id,
        health.status_code,
        models,
        error_message=combined_error,
    )
    return ProviderResult(health.status_code, models, combined_error)


def refresh_all(
    vault: Vault,
    keys: VaultKeyMaterial,
    *,
    record_ids: Iterable[int] | None = None,
    transport: httpx.BaseTransport | None = None,
) -> dict[int, ProviderResult]:
    results: dict[int, ProviderResult] = {}
    if record_ids is None:
        record_ids = [int(record["id"]) for record in vault.list_keys()]
    for record_id in record_ids:
        results[record_id] = refresh_key(vault, keys, record_id, transport=transport)
    return results
