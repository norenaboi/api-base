from __future__ import annotations

from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx

from api_base.providers import ProviderResult, check_key_health, fetch_models
from api_base.vault import Vault, VaultKeyMaterial


def _fetch_result(
    provider: str,
    api_key: str,
    check_model: str | None,
    transport: httpx.BaseTransport | None,
) -> ProviderResult:
    model_result = fetch_models(provider, api_key, transport=transport)
    models = model_result.models if model_result.status_code == 200 else []
    health = check_key_health(provider, api_key, model=check_model, transport=transport)
    return ProviderResult(
        health.status_code,
        models,
        health.error or model_result.error,
        health.comment,
    )


def _persist_result(vault: Vault, record_id: int, result: ProviderResult) -> None:
    vault.update_check_result(
        record_id,
        result.status_code,
        result.models,
        error_message=result.error,
        user_comment=result.comment,
    )


def refresh_key(
    vault: Vault,
    keys: VaultKeyMaterial,
    record_id: int,
    *,
    transport: httpx.BaseTransport | None = None,
) -> ProviderResult:
    record = vault.get_key(record_id)
    result = _fetch_result(
        str(record["typeofkey"]),
        vault.reveal_key(keys, record_id),
        str(record["check_model"]) if record.get("check_model") else None,
        transport,
    )
    _persist_result(vault, record_id, result)
    return result


def refresh_all(
    vault: Vault,
    keys: VaultKeyMaterial,
    *,
    record_ids: Iterable[int] | None = None,
    transport: httpx.BaseTransport | None = None,
    max_workers: int = 4,
) -> dict[int, ProviderResult]:
    if record_ids is None:
        records = vault.list_keys()
    else:
        records = [vault.get_key(record_id) for record_id in record_ids]

    work = {
        int(record["id"]): (
            str(record["typeofkey"]),
            vault.reveal_key(keys, int(record["id"])),
            str(record["check_model"]) if record.get("check_model") else None,
        )
        for record in records
    }
    results: dict[int, ProviderResult] = {}
    worker_count = min(max_workers, len(work))
    if worker_count == 0:
        return results

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(_fetch_result, provider, api_key, check_model, transport): record_id
            for record_id, (provider, api_key, check_model) in work.items()
        }
        for future in as_completed(futures):
            record_id = futures[future]
            try:
                result = future.result()
            except Exception as error:  # provider failures should not abort the remaining batch
                result = ProviderResult(None, [], str(error))
            results[record_id] = result

    for record_id, result in results.items():
        _persist_result(vault, record_id, result)
    return results
