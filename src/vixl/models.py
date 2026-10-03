"""Credential references, model discovery and conservative capability routing."""

import json
import os
from pathlib import Path
import tempfile

from filelock import FileLock

from .assets import read_bounded
from .commands import Parser
from .errors import require, VixlError

DEFAULTS = {
    "openai": {"type": "openai", "url": "https://api.openai.com/v1", "key_env": "OPENAI_API_KEY"},
    "anthropic": {"type": "anthropic", "key_env": "ANTHROPIC_API_KEY"},
    "mistral": {"type": "mistral", "url": "https://api.mistral.ai/v1", "key_env": "MISTRAL_API_KEY"},
    "meta": {"type": "meta", "url": "https://api.llama.com/v1", "key_env": "LLAMA_API_KEY"},
    "gemini": {
        "type": "gemini",
        "url": "https://generativelanguage.googleapis.com/v1beta",
        "key_env": "GEMINI_API_KEY",
    },
}
CAPABILITIES = ("plan", "describe", "detect", "ocr", "generate", "segment", "upscale", "background-remove")


def config_path():
    return Path(os.environ.get("VIXL_PROVIDERS", "~/.config/vixl/providers.json")).expanduser()


def load_config():
    path = config_path()
    value = json.loads(read_bounded(path, 1024 * 1024)) if path.exists() else {}
    require(
        isinstance(value, dict) and isinstance(value.get("providers", {}), dict),
        "Provider configuration must be an object",
    )
    return value


def configured():
    config = load_config()
    result = {name: dict(value) for name, value in DEFAULTS.items() if os.environ.get(value["key_env"])}
    result.update(config.get("providers", {}))
    return result


def save_provider(name, value):
    from .design import named

    named(name)
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(path) + ".lock"):
        config = load_config()
        config.setdefault("providers", {})[name] = value
        payload = json.dumps(config, ensure_ascii=False).encode()
        require(len(payload) <= 1024 * 1024, "Provider configuration exceeds limit", "resource_limit")
        fd, temp = tempfile.mkstemp(dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
            os.replace(temp, path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)


def model_capabilities(kind, item):
    ident = item.get("id", item.get("name", "")).lower()
    caps = item.get("capabilities", {})
    if isinstance(caps, list):
        return sorted(set(caps) & set(CAPABILITIES))
    if kind == "anthropic":
        return ["plan", "describe", "detect", "ocr"]
    if kind == "gemini":
        methods = item.get("supportedGenerationMethods", [])
        if "generateContent" in methods:
            if "gemma" in ident or ident.endswith("gemini-pro"):
                return ["plan"]
            return (
                ["plan", "describe", "detect", "ocr", "generate"]
                if "image" in ident
                else ["plan", "describe", "detect", "ocr"]
            )
        return []
    if kind == "openai":
        if ident.startswith(("gpt-image", "dall-e")):
            return ["generate"]
        if ident.startswith(("gpt-4", "gpt-5", "gpt-6", "chatgpt", "o1", "o3", "o4")) and not any(
            x in ident for x in ("audio", "realtime", "transcribe", "tts", "search")
        ):
            if (
                ident
                in (
                    "gpt-4",
                    "gpt-4-0314",
                    "gpt-4-0613",
                    "gpt-4-32k",
                    "gpt-4-32k-0314",
                    "gpt-4-32k-0613",
                    "o1-preview",
                    "o1-mini",
                )
                or "o3-mini" in ident
                or ("preview" in ident and "vision" not in ident and ident.startswith("gpt-4"))
            ):
                return ["plan"]
            return ["plan", "describe", "detect", "ocr"]
        return []
    if kind in ("mistral", "meta"):
        result = ["plan"] if caps.get("completion_chat", kind == "meta") else []
        if caps.get("vision") or (
            kind == "meta" and any(x in ident for x in ("scout", "maverick", "vision"))
        ):
            result.extend(["describe", "detect", "ocr"])
        return result
    return []


def catalog_provider(name, settings):
    from .ai import HTTPProvider, make_provider

    if settings.get("type") == "anthropic":
        config = dict(settings)
        url = config.get("url", "https://api.anthropic.com").rstrip("/")
        config["url"] = url if url.endswith("/v1") else url + "/v1"
        config["key_header"] = "x-api-key"
        config.setdefault("key_env", "ANTHROPIC_API_KEY")
        backend = HTTPProvider(name, config)
        backend.headers["anthropic-version"] = "2023-06-01"
        return backend
    return make_provider(name, settings)


def discover(backend):
    kind = backend.config.get("type", "http")
    if kind == "comfyui":
        require(
            False,
            "ComfyUI capabilities are defined by configured workflows; use explicit models/capabilities",
        )
    if kind == "automatic1111":
        value = json.loads(backend.request("GET", "/sdapi/v1/sd-models"))
        require(isinstance(value, list), "Invalid model catalog", "provider_error")
        return [{"id": item["title"], "capabilities": ["generate"]} for item in value]
    route = "/models"
    items, cursor, seen = [], None, set()
    for _ in range(20):
        params = {}
        if kind == "gemini":
            params["pageSize"] = 100
            if cursor:
                params["pageToken"] = cursor
        elif kind == "anthropic":
            params["limit"] = 100
            if cursor:
                params["after_id"] = cursor
        result = backend.json("GET", route, params=params)
        page = result.get("models" if kind == "gemini" else "data", [])
        require(isinstance(page, list), "Invalid model catalog", "provider_error")
        for item in page:
            require(isinstance(item, dict), "Invalid model entry", "provider_error")
            ident = item.get("id", item.get("name"))
            require(isinstance(ident, str) and 0 < len(ident) <= 300, "Invalid model ID", "provider_error")
            if ident not in seen:
                seen.add(ident)
                items.append({"id": ident, "capabilities": model_capabilities(kind, item)})
        require(len(items) <= 2000, "Model catalog exceeds limit", "resource_limit")
        cursor = (
            result.get("nextPageToken")
            if kind == "gemini"
            else (result.get("last_id") if kind == "anthropic" and result.get("has_more") else None)
        )
        if not cursor:
            return items
    raise VixlError("resource_limit", "Model pagination exceeds limit")


def refresh(name):
    settings = configured().get(name, DEFAULTS.get(name))
    require(settings is not None, f"Unknown provider: {name}")
    settings = dict(settings)
    settings["models"] = discover(catalog_provider(name, settings))
    save_provider(name, settings)
    return settings["models"]


def route(capability, name=None, model=None):
    from .ai import provider

    config = load_config()
    selected = name or os.environ.get("VIXL_AI_PROVIDER") or config.get("default")
    candidates = configured()
    if name and name in DEFAULTS and name not in candidates:
        candidates[name] = DEFAULTS[name]
    order = ([selected] if selected else []) + [n for n in candidates if n != selected]
    failures = []
    for candidate in order:
        if name and candidate != name:
            continue
        try:
            backend = provider(candidate)
            if not hasattr(backend, "config"):
                return backend
            settings = backend.config
            models = settings.get("models")
            # Preserve official SDK login/profile inference when no HTTP discovery key exists.
            sdk_only = settings.get("type") == "anthropic" and not os.environ.get(
                settings.get("key_env", "ANTHROPIC_API_KEY")
            )
            if models is None and settings.get("type") in DEFAULTS and not sdk_only:
                models = refresh(candidate)
                settings = provider(candidate).config
        except VixlError as exc:
            if name:
                raise
            failures.append(exc)
            continue
        if models is not None:
            matches = [
                m
                for m in models
                if capability in m.get("capabilities", []) and (not model or m["id"] == model)
            ]
            if not matches:
                continue
            preferred = model or settings.get("model" if capability == "generate" else "reasoning_model")
            chosen = next((m["id"] for m in matches if m["id"] == preferred), matches[0]["id"])
            settings = dict(settings, model=chosen, reasoning_model=chosen, vision_model=chosen)
            backend = type(backend)(candidate, settings)
        elif settings.get("capabilities") and capability not in settings["capabilities"]:
            continue
        return backend
    if failures and len(failures) == len(order):
        raise failures[0]
    if not order:
        return provider(name)  # Preserve the existing actionable configuration error.
    raise VixlError(
        "unsupported_capability",
        f"No configured model supports {capability}"
        + (f" with model {model}" if model else "")
        + ". Refresh models or configure an appropriate provider.",
    )


def discovery_command(cmd, args):
    p = Parser(prog=f"vixl {cmd}")
    if cmd == "providers":
        p.add_argument("action", nargs="?", choices=["list", "add", "refresh"], default="list")
        p.add_argument("name", nargs="?")
        p.add_argument("--type", choices=[*DEFAULTS, "http", "midjourney"])
        p.add_argument("--key-env")
        p.add_argument("--url")
    else:
        p.add_argument("--provider")
        p.add_argument("--capability", choices=CAPABILITIES)
        p.add_argument("--refresh", action="store_true")
    a = p.parse_args(args)
    if cmd == "providers" and a.action == "add":
        require(
            a.name and a.type and a.key_env, "Use providers add NAME --type TYPE --key-env ENV [--url URL]"
        )
        require(
            a.type != "midjourney" or a.url,
            "Midjourney has no supported public API; provide an HTTP gateway URL using --url",
        )
        settings = dict(DEFAULTS.get(a.type, {"type": "http"}), key_env=a.key_env)
        if a.url:
            settings["url"] = a.url
        require(settings.get("url") or a.type == "anthropic", "Provide a provider URL")
        # Discover before committing configuration; failed keys never replace a working provider.
        settings["models"] = discover(catalog_provider(a.name, settings))
        save_provider(a.name, settings)
        return {"provider": a.name, "models": settings["models"]}
    if cmd == "providers" and a.action == "refresh":
        require(a.name, "Provide a provider name")
        return {"provider": a.name, "models": refresh(a.name)}
    items = configured()
    if cmd == "providers":
        return {
            "providers": [
                {
                    "name": n,
                    "type": s.get("type", "http"),
                    "credential_ready": bool(os.environ.get(s.get("key_env", "")))
                    if s.get("key_env")
                    else True,
                    "model_count": len(s.get("models", [])),
                }
                for n, s in items.items()
            ],
            "supported": list(DEFAULTS),
            "midjourney": "Requires a configured HTTP gateway; no supported public model API.",
        }
    names = [a.provider] if a.provider else list(items)
    output = []
    for name in names:
        settings = items.get(name, DEFAULTS.get(name))
        require(settings is not None, f"Unknown provider: {name}")
        models = refresh(name) if a.refresh or "models" not in settings else settings["models"]
        output.extend(
            {"provider": name, **m}
            for m in models
            if not a.capability or a.capability in m.get("capabilities", [])
        )
    return {"models": output}
