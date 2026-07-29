from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

DEFAULT_TIMEOUT_SECONDS = 15.0
REPLICATE_MODELS_URL = "https://api.replicate.com/v1/models"
REPLICATE_PREDICTIONS_URL = (
    "https://api.replicate.com/v1/models/anthropic/claude-3.7-sonnet/predictions"
)
REPLICATE_MAX_MODEL_PAGES = 10
REPLICATE_MAX_MODELS = 1000
REPLICATE_REFRESH_PROMPT = (
    "Give me a recipe for pancakes that could feed all of California."
)


@dataclass(frozen=True, slots=True)
class ProviderResult:
    status_code: int | None
    models: list[str]
    error: str | None = None
    comment: str | None = None
    openrouter_tier: str | None = None


class QuotaExceededError(Exception):
    """Raised when a provider reports the account/quota is exhausted."""


class RateLimitedError(Exception):
    """Raised when a provider reports rate limiting."""


class InvalidKeyError(Exception):
    """Raised when a provider rejects the API key."""


def _format_amount(value: object) -> str:
    if value is None:
        return "N/A"
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def _auth_headers(provider: str, api_key: str) -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "User-Agent": "api-base/0.1",
    }
    if provider == "anthropic":
        headers.update(
            {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
        )
    elif provider == "huggingface":
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        headers["content-type"] = "application/json"
    elif provider == "openrouter":
        headers["Authorization"] = f"Bearer {api_key}"
        headers["HTTP-Referer"] = "http://localhost"
        headers["X-Title"] = "API Base"
        headers["content-type"] = "application/json"
    elif provider == "gemini":
        headers["content-type"] = "application/json"
    else:
        headers["Authorization"] = f"Bearer {api_key}"
        headers["content-type"] = "application/json"
    return headers


def _minimal_chat_payload(provider: str, model: str | None = None) -> tuple[str, dict[str, object]]:
    if provider == "openai":
        return (
            "https://api.openai.com/v1/responses",
            {
                "model": model or "gpt-5.5",
                "input": "ping",
                "max_output_tokens": 16,
                "store": False,
            },
        )
    if provider == "anthropic":
        return (
            "https://api.anthropic.com/v1/messages",
            {
                "model": model or "claude-haiku-4-5",
                "max_tokens": 1,
                "messages": [{"role": "user", "content": "ping"}],
            },
        )
    if provider == "xai":
        return (
            "https://api.x.ai/v1/chat/completions",
            {
                "model": model or "grok-4.3",
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
            },
        )
    if provider == "groq":
        return (
            "https://api.groq.com/openai/v1/chat/completions",
            {
                "model": model or "openai/gpt-oss-120b",
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
            },
        )
    if provider == "zhipu":
        return (
            "https://open.bigmodel.cn/api/paas/v4/chat/completions",
            {
                "model": model or "glm-4.5-flash",
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
            },
        )
    if provider == "moonshot":
        return (
            "https://api.moonshot.cn/v1/chat/completions",
            {
                "model": model or "moonshot-v1-8k",
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
            },
        )
    if provider == "dashscope":
        return (
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            {
                "model": model or "qwen-turbo",
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
            },
        )
    if provider == "gemini":
        model_name = model or "gemini-2.5-flash"
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
        )
        return (
            url,
            {
                "contents": [{"parts": [{"text": "ping"}]}],
                "generationConfig": {"maxOutputTokens": 1},
            },
        )
    if provider == "huggingface":
        return (
            "https://router.huggingface.co/v1/chat/completions",
            {
                "model": model or "deepseek-ai/DeepSeek-R1-0528",
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
            },
        )
    raise ValueError(f"Unsupported provider for health check: {provider}")


def _classify_error(provider: str, response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = {}

    error_obj = payload.get("error") if isinstance(payload, dict) else None
    error_message = ""
    if isinstance(error_obj, dict):
        error_message = (error_obj.get("message") or "").lower()
    elif isinstance(error_obj, str):
        error_message = error_obj.lower()
    elif isinstance(payload, dict) and "error" in payload:
        error_message = str(payload["error"]).lower()

    if (
        response.status_code == 402
        or "insufficient_quota" in error_message
        or "quota" in error_message
    ):
        return "quota_exhausted"
    if response.status_code == 429:
        return "rate_limited"
    if response.status_code == 401:
        return "invalid_key"
    if response.status_code == 403:
        return "forbidden"
    if response.status_code >= 500:
        return "server_error"
    if response.status_code >= 400:
        return "client_error"
    return "unknown"


def _failure_result(provider: str, response: httpx.Response) -> ProviderResult:
    category = _classify_error(provider, response)
    messages = {
        "rate_limited": "Rate limited. Slow down and retry later.",
        "invalid_key": "Invalid or revoked API key.",
        "forbidden": "API key is valid but access to this model or resource is forbidden.",
        "quota_exhausted": "Quota exhausted. Add credits or switch key.",
        "server_error": "Provider server error.",
        "client_error": f"Provider returned HTTP {response.status_code}.",
        "unknown": f"Provider returned HTTP {response.status_code}.",
    }
    return ProviderResult(response.status_code, [], messages.get(category, messages["unknown"]))


def _check_deepseek_balance(
    api_key: str,
    *,
    transport: httpx.BaseTransport | None = None,
) -> ProviderResult:
    headers = _auth_headers("deepseek", api_key)
    try:
        with httpx.Client(
            transport=transport,
            timeout=DEFAULT_TIMEOUT_SECONDS,
            follow_redirects=False,
        ) as client:
            response = client.get("https://api.deepseek.com/user/balance", headers=headers)
    except httpx.HTTPError:
        return ProviderResult(None, [], "Could not reach the provider endpoint.")

    if response.status_code != 200:
        return _failure_result("deepseek", response)

    try:
        data = response.json()
    except ValueError:
        return ProviderResult(200, [], "Provider returned an unreadable balance response.")

    parts = [
        f"{_format_amount(balance.get('total_balance'))} {balance.get('currency', '')}".strip()
        for balance in data.get("balance_infos", [])
        if isinstance(balance, dict)
    ]
    comment = ", ".join(parts) if parts else "no balance info"
    return ProviderResult(200, [], None, comment)


_OPENROUTER_RESET_PERIODS = {"daily": "day", "weekly": "week", "monthly": "month"}


def _is_safe_replicate_stream_url(url: str) -> bool:
    parsed = urlsplit(url)
    try:
        port = parsed.port
    except ValueError:
        return False
    hostname = parsed.hostname or ""
    return (
        parsed.scheme == "https"
        and port in {None, 443}
        and parsed.username is None
        and parsed.password is None
        and (hostname == "replicate.com" or hostname.endswith(".replicate.com"))
    )


def _check_replicate_prediction(
    api_key: str,
    *,
    transport: httpx.BaseTransport | None = None,
) -> ProviderResult:
    headers = _auth_headers("replicate", api_key)
    try:
        with httpx.Client(
            transport=transport,
            timeout=DEFAULT_TIMEOUT_SECONDS,
            follow_redirects=False,
        ) as client:
            prediction_response = client.post(
                REPLICATE_PREDICTIONS_URL,
                headers=headers,
                json={
                    "stream": True,
                    "input": {"prompt": REPLICATE_REFRESH_PROMPT},
                },
            )
            if not 200 <= prediction_response.status_code < 300:
                return _failure_result("replicate", prediction_response)

            try:
                payload = prediction_response.json()
            except ValueError:
                return ProviderResult(
                    prediction_response.status_code,
                    [],
                    "Provider returned an unreadable prediction response.",
                )
            urls = payload.get("urls") if isinstance(payload, dict) else None
            stream_url = urls.get("stream") if isinstance(urls, dict) else None
            if not isinstance(stream_url, str) or not _is_safe_replicate_stream_url(stream_url):
                return ProviderResult(
                    prediction_response.status_code,
                    [],
                    "Provider returned an invalid prediction stream URL.",
                )

            stream_response = client.get(
                stream_url,
                headers={
                    "Accept": "text/event-stream",
                    "Cache-Control": "no-store",
                    "User-Agent": "api-base/0.1",
                },
            )
    except httpx.HTTPError:
        return ProviderResult(None, [], "Could not reach the provider endpoint.")

    if not 200 <= stream_response.status_code < 300:
        return _failure_result("replicate", stream_response)
    return ProviderResult(stream_response.status_code, [])


def _check_openrouter_key(
    api_key: str,
    *,
    transport: httpx.BaseTransport | None = None,
) -> ProviderResult:
    headers = _auth_headers("openrouter", api_key)
    try:
        with httpx.Client(
            transport=transport,
            timeout=DEFAULT_TIMEOUT_SECONDS,
            follow_redirects=False,
        ) as client:
            response = client.get("https://openrouter.ai/api/v1/key", headers=headers)
    except httpx.HTTPError:
        return ProviderResult(None, [], "Could not reach the provider endpoint.")

    if response.status_code != 200:
        return _failure_result("openrouter", response)

    try:
        data = response.json().get("data", {})
    except ValueError:
        return ProviderResult(200, [], "Provider returned an unreadable key response.")
    if not isinstance(data, dict):
        data = {}

    is_free_tier = data.get("is_free_tier")
    tier = (
        "free"
        if is_free_tier is True
        else "paid"
        if is_free_tier is False
        else None
    )

    limit = data.get("limit")
    if limit is None:
        limit_part = "unlimited"
    else:
        limit_part = f"{limit}$"
        reset = data.get("limit_reset")
        if reset:
            period = _OPENROUTER_RESET_PERIODS.get(str(reset).lower(), str(reset))
            limit_part += f"/{period}"

    total_spent = _format_amount(data.get("usage"))
    tier_label = f"{tier} tier" if tier else "unknown tier"
    comment = f"{tier_label} - {limit_part} - {total_spent}$"

    try:
        with httpx.Client(
            transport=transport,
            timeout=DEFAULT_TIMEOUT_SECONDS,
            follow_redirects=False,
        ) as client:
            response = client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json={
                    "model": "mistralai/ministral-3b-2512",
                    "messages": [{"role": "user", "content": "hey"}],
                    "max_tokens": 1,
                },
            )
    except httpx.HTTPError:
        return ProviderResult(
            status_code=None,
            models=[],
            error="Could not reach the provider endpoint.",
            comment=comment,
            openrouter_tier=tier,
        )

    if response.status_code != 200:
        failure = _failure_result("openrouter", response)
        return ProviderResult(
            status_code=failure.status_code,
            models=[],
            error=failure.error,
            comment=comment,
            openrouter_tier=tier,
        )
    return ProviderResult(
        status_code=200,
        models=[],
        comment=comment,
        openrouter_tier=tier,
    )


def check_key_health(
    provider: str,
    api_key: str,
    *,
    model: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> ProviderResult:
    # DeepSeek and OpenRouter expose account endpoints, so their health check
    # is a cheap GET that also yields balance/limit info for the key comment.
    if provider == "deepseek":
        return _check_deepseek_balance(api_key, transport=transport)
    if provider == "openrouter":
        return _check_openrouter_key(api_key, transport=transport)
    if provider == "replicate":
        return _check_replicate_prediction(api_key, transport=transport)

    try:
        url, payload = _minimal_chat_payload(provider, model)
    except ValueError as error:
        return ProviderResult(None, [], str(error))

    headers = _auth_headers(provider, api_key)

    if provider == "gemini":
        url = f"{url}?key={api_key}"

    try:
        with httpx.Client(
            transport=transport,
            timeout=DEFAULT_TIMEOUT_SECONDS,
            follow_redirects=False,
        ) as client:
            response = client.post(url, headers=headers, json=payload)
    except httpx.HTTPError:
        return ProviderResult(None, [], "Could not reach the provider endpoint.")

    if response.status_code == 200:
        return ProviderResult(200, [], None)

    return _failure_result(provider, response)


def _is_safe_replicate_models_url(url: str) -> bool:
    parsed = urlsplit(url)
    try:
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname == "api.replicate.com"
        and port in {None, 443}
        and parsed.username is None
        and parsed.password is None
        and parsed.path == "/v1/models"
    )


def _fetch_replicate_models(
    api_key: str,
    *,
    transport: httpx.BaseTransport | None = None,
) -> ProviderResult:
    headers = _auth_headers("replicate", api_key)
    models: set[str] = set()
    visited_urls: set[str] = set()
    url: str | None = REPLICATE_MODELS_URL

    try:
        with httpx.Client(
            transport=transport,
            timeout=DEFAULT_TIMEOUT_SECONDS,
            follow_redirects=False,
        ) as client:
            for page_number in range(REPLICATE_MAX_MODEL_PAGES):
                if url is None:
                    return ProviderResult(200, sorted(models))
                if url in visited_urls:
                    return ProviderResult(
                        200, sorted(models), "Provider returned a pagination loop."
                    )
                if not _is_safe_replicate_models_url(url):
                    return ProviderResult(
                        200,
                        sorted(models),
                        "Provider returned an unsafe models pagination URL.",
                    )

                visited_urls.add(url)
                response = client.get(url, headers=headers)
                if response.status_code != 200:
                    return ProviderResult(
                        response.status_code,
                        [],
                        f"Provider returned HTTP {response.status_code}.",
                    )

                try:
                    payload = response.json()
                except ValueError:
                    return ProviderResult(
                        200, [], "Provider returned an unreadable models response."
                    )
                if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
                    return ProviderResult(
                        200, [], "Provider returned an unreadable models response."
                    )

                for item_index, item in enumerate(payload["results"]):
                    if not isinstance(item, dict):
                        continue
                    owner = item.get("owner")
                    name = item.get("name")
                    if not isinstance(owner, str) or not isinstance(name, str):
                        continue
                    owner = owner.strip()
                    name = name.strip()
                    if owner and name:
                        models.add(f"{owner}/{name}")
                    if len(models) >= REPLICATE_MAX_MODELS:
                        has_unread_items = item_index < len(payload["results"]) - 1
                        error = (
                            f"Model list was truncated after {REPLICATE_MAX_MODELS} models."
                            if has_unread_items or payload.get("next") is not None
                            else None
                        )
                        return ProviderResult(200, sorted(models)[:REPLICATE_MAX_MODELS], error)

                next_url = payload.get("next")
                if next_url is None:
                    return ProviderResult(200, sorted(models))
                if not isinstance(next_url, str):
                    return ProviderResult(
                        200,
                        sorted(models),
                        "Provider returned an invalid models pagination URL.",
                    )
                url = next_url

                if page_number == REPLICATE_MAX_MODEL_PAGES - 1:
                    return ProviderResult(
                        200,
                        sorted(models),
                        f"Model list was truncated after {REPLICATE_MAX_MODEL_PAGES} pages.",
                    )
    except httpx.HTTPError:
        return ProviderResult(None, [], "Could not reach the provider models endpoint.")

    return ProviderResult(200, sorted(models))


def fetch_models(
    provider: str,
    api_key: str,
    *,
    transport: httpx.BaseTransport | None = None,
) -> ProviderResult:
    if provider == "replicate":
        return _fetch_replicate_models(api_key, transport=transport)

    endpoints = {
        "openai": "https://api.openai.com/v1/models",
        "deepseek": "https://api.deepseek.com/models",
        "anthropic": "https://api.anthropic.com/v1/models?limit=1000",
        "xai": "https://api.x.ai/v1/models",
        "gemini": "https://generativelanguage.googleapis.com/v1beta/models",
        "huggingface": "https://huggingface.co/api/models?limit=1000",
        "groq": "https://api.groq.com/openai/v1/models",
        "openrouter": "https://openrouter.ai/api/v1/models",
        "zhipu": "https://open.bigmodel.cn/api/paas/v4/models",
        "moonshot": "https://api.moonshot.cn/v1/models",
        "dashscope": "https://dashscope.aliyuncs.com/compatible-mode/v1/models",
    }
    if provider not in endpoints:
        raise ValueError(f"Unsupported provider: {provider}")

    headers = {
        "Accept": "application/json",
        "User-Agent": "api-base/0.1",
    }
    if provider == "anthropic":
        headers.update(
            {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            }
        )
    elif provider == "gemini":
        pass
    elif provider == "huggingface":
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
    elif provider == "openrouter":
        headers["Authorization"] = f"Bearer {api_key}"
        headers["HTTP-Referer"] = "http://localhost"
        headers["X-Title"] = "API Base"
    else:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        with httpx.Client(
            transport=transport,
            timeout=DEFAULT_TIMEOUT_SECONDS,
            follow_redirects=False,
        ) as client:
            url = endpoints[provider]
            if provider == "gemini":
                url = f"{url}?key={api_key}"
            response = client.get(url, headers=headers)
    except httpx.HTTPError:
        return ProviderResult(None, [], "Could not reach the provider models endpoint.")

    if response.status_code != 200:
        return ProviderResult(
            response.status_code,
            [],
            f"Provider returned HTTP {response.status_code}.",
        )

    try:
        payload = response.json()
        if provider == "gemini":
            models = sorted(
                {
                    item["name"].removeprefix("models/")
                    for item in payload.get("models", [])
                    if isinstance(item, dict) and isinstance(item.get("name"), str)
                }
            )
        elif provider == "huggingface":
            models = sorted(
                {
                    item["id"]
                    for item in payload
                    if isinstance(item, dict) and isinstance(item.get("id"), str)
                }
            )
        else:
            models = sorted(
                {
                    item["id"]
                    for item in payload.get("data", [])
                    if isinstance(item, dict) and isinstance(item.get("id"), str)
                }
            )
    except (TypeError, ValueError):
        return ProviderResult(200, [], "Provider returned an unreadable models response.")
    return ProviderResult(200, models)
