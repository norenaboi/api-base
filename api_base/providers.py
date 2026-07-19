from __future__ import annotations

from dataclasses import dataclass

import httpx

DEFAULT_TIMEOUT_SECONDS = 15.0


@dataclass(frozen=True, slots=True)
class ProviderResult:
    status_code: int | None
    models: list[str]
    error: str | None = None


class QuotaExceededError(Exception):
    """Raised when a provider reports the account/quota is exhausted."""


class RateLimitedError(Exception):
    """Raised when a provider reports rate limiting."""


class InvalidKeyError(Exception):
    """Raised when a provider rejects the API key."""


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
            "https://api.openai.com/v1/chat/completions",
            {
                "model": model or "gpt-5.5",
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
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
    if provider == "deepseek":
        return (
            "https://api.deepseek.com/chat/completions",
            {
                "model": model or "deepseek-v4-flash",
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
    if provider == "openrouter":
        return (
            "https://openrouter.ai/api/v1/chat/completions",
            {
                "model": model or "deepseek/deepseek-r1-0528",
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
    if provider == "gemini":
        model_name = model or "gemini-3.1-pro-preview"
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

    if response.status_code == 429:
        return "rate_limited"
    if response.status_code == 401 or response.status_code == 403:
        return "invalid_key"
    if (
        response.status_code == 402
        or "insufficient_quota" in error_message
        or "quota" in error_message
    ):
        return "quota_exhausted"
    if response.status_code >= 500:
        return "server_error"
    if response.status_code >= 400:
        return "client_error"
    return "unknown"


def check_key_health(
    provider: str,
    api_key: str,
    *,
    model: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> ProviderResult:
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

    category = _classify_error(provider, response)
    messages = {
        "rate_limited": "Rate limited. Slow down and retry later.",
        "invalid_key": "Invalid or revoked API key.",
        "quota_exhausted": "Quota exhausted. Add credits or switch key.",
        "server_error": "Provider server error.",
        "client_error": f"Provider returned HTTP {response.status_code}.",
        "unknown": f"Provider returned HTTP {response.status_code}.",
    }
    return ProviderResult(response.status_code, [], messages.get(category, messages["unknown"]))


def fetch_models(
    provider: str,
    api_key: str,
    *,
    transport: httpx.BaseTransport | None = None,
) -> ProviderResult:
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
