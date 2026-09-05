"""AI provider registry + adapters.

Each adapter takes (api_key, base_url, model, system, messages, max_tokens) and
returns a NORMALIZED result so the rest of the app never cares which provider
answered:
    {ok: bool, text: str, usage: {input_tokens, output_tokens}, error, error_kind}

Kinds:
  - anthropic  (Claude)
  - openai     (OpenAI + any OpenAI-compatible proxy: Agent Router, Forge)
  - gemini     (Google Generative Language API)
"""

from __future__ import annotations

import httpx

# provider_id -> metadata. base_url is a default; OpenAI-compatible proxies
# (agent_router/forge) require the CEO to supply their own base_url.
PROVIDERS: dict[str, dict] = {
    "claude": {
        "display_name": "Claude (Anthropic)", "kind": "anthropic",
        "base_url": "https://api.anthropic.com",
        "models": ["claude-opus-4-8", "claude-sonnet-5", "claude-haiku-4-5-20251001"],
        "needs_base_url": False,
    },
    "openai": {
        "display_name": "OpenAI", "kind": "openai",
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-5", "gpt-4.1", "gpt-4o", "gpt-4o-mini"],
        "needs_base_url": False,
    },
    "gemini": {
        "display_name": "Google Gemini", "kind": "gemini",
        "base_url": "https://generativelanguage.googleapis.com",
        "models": ["gemini-2.5-pro", "gemini-2.5-flash"],
        "needs_base_url": False,
    },
    "agent_router": {
        "display_name": "Agent Router (OpenAI-compatible)", "kind": "openai",
        "base_url": "", "models": [], "needs_base_url": True,
    },
    "forge": {
        "display_name": "Forge (OpenAI-compatible)", "kind": "openai",
        "base_url": "", "models": [], "needs_base_url": True,
    },
}

# Rough $/1M tokens (input, output) for cost estimation. Unknown -> (0,0).
_PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-4-8": (5.0, 25.0), "claude-sonnet-5": (3.0, 15.0), "claude-haiku-4-5-20251001": (0.8, 4.0),
    "gpt-5": (5.0, 15.0), "gpt-4.1": (2.5, 10.0), "gpt-4o": (2.5, 10.0), "gpt-4o-mini": (0.15, 0.6),
    "gemini-2.5-pro": (1.25, 10.0), "gemini-2.5-flash": (0.3, 2.5),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    pin, pout = _PRICES.get(model, (0.0, 0.0))
    return round((input_tokens / 1_000_000) * pin + (output_tokens / 1_000_000) * pout, 6)


def _norm(ok, text="", inp=0, out=0, error="", kind=""):
    return {"ok": ok, "text": text, "usage": {"input_tokens": inp, "output_tokens": out}, "error": error, "error_kind": kind}


async def _call_anthropic(key, base_url, model, system, messages, max_tokens):
    async with httpx.AsyncClient(timeout=90) as c:
        r = await c.post(
            f"{base_url}/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": model, "max_tokens": max_tokens, "system": system, "messages": messages},
        )
    if r.status_code == 200:
        d = r.json()
        text = "".join(b.get("text", "") for b in (d.get("content") or []) if b.get("type") == "text").strip()
        u = d.get("usage") or {}
        return _norm(True, text, u.get("input_tokens", 0), u.get("output_tokens", 0))
    return _http_error(r)


async def _call_openai(key, base_url, model, system, messages, max_tokens):
    # OpenAI-compatible chat completions (works for OpenAI, Agent Router, Forge).
    oai_messages = [{"role": "system", "content": system}] + messages
    async with httpx.AsyncClient(timeout=90) as c:
        r = await c.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"authorization": f"Bearer {key}", "content-type": "application/json"},
            json={"model": model, "messages": oai_messages, "max_tokens": max_tokens},
        )
    if r.status_code == 200:
        d = r.json()
        choice = (d.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        # content can be null (refusal / reasoning-only), a string, or a list of parts.
        content = msg.get("content")
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        text = (content or "").strip()
        if not text:
            # Fall back to a refusal message or a clear reason so the agent never crashes.
            text = (msg.get("refusal") or "").strip()
            if not text:
                fr = choice.get("finish_reason") or "empty"
                text = f"(The model returned no text — finish_reason: {fr}. Try a different model or rephrase.)"
        u = d.get("usage") or {}
        return _norm(True, text, u.get("prompt_tokens", 0), u.get("completion_tokens", 0))
    return _http_error(r)


async def _call_gemini(key, base_url, model, system, messages, max_tokens):
    contents = [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]} for m in messages]
    async with httpx.AsyncClient(timeout=90) as c:
        r = await c.post(
            f"{base_url}/v1beta/models/{model}:generateContent?key={key}",
            headers={"content-type": "application/json"},
            json={"systemInstruction": {"parts": [{"text": system}]}, "contents": contents,
                  "generationConfig": {"maxOutputTokens": max_tokens}},
        )
    if r.status_code == 200:
        d = r.json()
        cand = (d.get("candidates") or [{}])[0]
        text = "".join(p.get("text", "") for p in (cand.get("content", {}).get("parts") or [])).strip()
        um = d.get("usageMetadata", {})
        return _norm(True, text, um.get("promptTokenCount", 0), um.get("candidatesTokenCount", 0))
    return _http_error(r)


def _http_error(r):
    if r.status_code in (401, 403):
        return _norm(False, error="Invalid or unauthorized API key.", kind="invalid_key")
    if r.status_code == 429:
        return _norm(False, error="Rate limited by provider.", kind="rate_limited")
    if r.status_code >= 500:
        return _norm(False, error=f"Provider server error ({r.status_code}).", kind="server")
    detail = ""
    try:
        detail = str(r.json().get("error", {}))[:160]
    except Exception:  # noqa: BLE001
        detail = r.text[:160]
    return _norm(False, error=f"Provider error {r.status_code}: {detail}", kind="unknown")


_ADAPTERS = {"anthropic": _call_anthropic, "openai": _call_openai, "gemini": _call_gemini}


async def list_models(provider_id, key, base_url):
    """Fetch the available model ids for a provider. Never raises.

    Returns {"ok": bool, "models": [ids], "error": str}. OpenAI-compatible
    providers (incl. OpenRouter/Forge/Agent Router) expose GET {base}/models;
    Anthropic and Gemini have their own list endpoints.
    """
    meta = PROVIDERS.get(provider_id)
    if not meta:
        return {"ok": False, "models": [], "error": f"Unknown provider '{provider_id}'."}
    base = (base_url or meta["base_url"]).rstrip("/")
    kind = meta["kind"]
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            if kind == "openai":
                r = await c.get(f"{base}/models", headers={"Authorization": f"Bearer {key}"})
                if r.status_code != 200:
                    return {"ok": False, "models": [], "error": f"{r.status_code}: {r.text[:150]}"}
                data = r.json().get("data", [])
                ids = sorted({m.get("id", "") for m in data if m.get("id")})
                return {"ok": True, "models": ids, "error": ""}
            if kind == "anthropic":
                r = await c.get(f"{base}/v1/models", headers={"x-api-key": key, "anthropic-version": "2023-06-01"})
                if r.status_code != 200:
                    return {"ok": False, "models": [], "error": f"{r.status_code}: {r.text[:150]}"}
                data = r.json().get("data", [])
                ids = [m.get("id", "") for m in data if m.get("id")]
                return {"ok": True, "models": ids, "error": ""}
            if kind == "gemini":
                r = await c.get(f"{base}/v1beta/models?key={key}")
                if r.status_code != 200:
                    return {"ok": False, "models": [], "error": f"{r.status_code}: {r.text[:150]}"}
                out = []
                for m in r.json().get("models", []):
                    if "generateContent" in (m.get("supportedGenerationMethods") or []):
                        out.append(m.get("name", "").replace("models/", ""))
                return {"ok": True, "models": [x for x in out if x], "error": ""}
        return {"ok": False, "models": [], "error": f"No model listing for kind '{kind}'."}
    except (httpx.TimeoutException, httpx.ConnectError) as exc:
        return {"ok": False, "models": [], "error": f"Connection failed: {type(exc).__name__}"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "models": [], "error": str(exc)[:200]}


async def provider_call(provider_id, key, base_url, model, system, messages, max_tokens):
    """Dispatch to the right adapter. Never raises."""
    meta = PROVIDERS.get(provider_id)
    if not meta:
        return _norm(False, error=f"Unknown provider '{provider_id}'.", kind="unknown")
    adapter = _ADAPTERS[meta["kind"]]
    try:
        return await adapter(key, base_url or meta["base_url"], model, system, messages, max_tokens)
    except (httpx.TimeoutException, httpx.ConnectError) as exc:
        return _norm(False, error=f"Connection failed: {type(exc).__name__}", kind="timeout")
    except Exception as exc:  # noqa: BLE001
        return _norm(False, error=f"{exc}", kind="unknown")
