"""Smart model routing — automatically picks the best available provider.

Priority order:
    1. Local GGUF model (free, private, no network)
    2. Ollama (free, local, requires Ollama running)
    3. Free-tier APIs: Groq free, Gemini free (requires API key)
    4. Paid APIs: OpenAI, Anthropic, OpenRouter, Together (only if allowed)

Usage:
    router = ModelRouter(config)
    provider = await router.route(messages, max_tokens=1024)
    response = await provider.generate(messages)
"""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

import asyncio
import enum
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import aiohttp

from trio.providers.base import BaseProvider, ProviderRegistry, register_all_providers

logger = logging.getLogger(__name__)


# ── Routing Strategy ─────────────────────────────────────────────────────────

class RoutingStrategy(enum.Enum):
    """How the router selects a provider."""
    LOCAL_ONLY = "local_only"        # Only use local models (GGUF + Ollama)
    FREE_FIRST = "free_first"        # Local → free APIs → paid (default)
    BALANCED = "balanced"            # Weight speed + cost + quality
    QUALITY_FIRST = "quality_first"  # Prefer best quality (paid APIs first)


# ── Cost estimates (USD per 1M tokens, approximate) ──────────────────────────

COST_PER_MILLION_TOKENS: dict[str, dict[str, float]] = {
    "local": {"input": 0.0, "output": 0.0},
    "ollama": {"input": 0.0, "output": 0.0},
    "groq": {"input": 0.0, "output": 0.0},          # free tier
    "gemini": {"input": 0.0, "output": 0.0},         # free tier
    "openai": {"input": 2.50, "output": 10.00},      # GPT-4o
    "anthropic": {"input": 3.00, "output": 15.00},   # Claude Sonnet
    "openrouter": {"input": 2.00, "output": 8.00},   # varies
    "together": {"input": 0.80, "output": 0.80},     # open-source models
    "deepseek": {"input": 0.14, "output": 0.28},
    "siliconflow": {"input": 0.50, "output": 0.50},
    "minimax": {"input": 1.00, "output": 1.00},
    "moonshot": {"input": 1.00, "output": 1.00},
    "dashscope": {"input": 0.50, "output": 0.50},
    "custom": {"input": 0.0, "output": 0.0},
}

# Providers considered "free" (no cost to user)
FREE_PROVIDERS = frozenset({"local", "trio", "ollama", "groq", "gemini"})

# Providers that are purely local (no network, no API key)
LOCAL_PROVIDERS = frozenset({"local", "trio"})

# Default fallback order for FREE_FIRST strategy
DEFAULT_FALLBACK_ORDER = [
    "local", "ollama", "groq", "gemini",
    "deepseek", "together", "openrouter", "openai", "anthropic",
]


@dataclass
class ProviderStatus:
    """Health/availability status of a single provider."""
    name: str
    available: bool = False
    healthy: bool = False
    is_local: bool = False
    is_free: bool = False
    has_api_key: bool = False
    last_check: float = 0.0
    latency_ms: float = 0.0
    error: str = ""
    models: list[str] = field(default_factory=list)


# ── Model Router ─────────────────────────────────────────────────────────────

class ModelRouter:
    """Smart provider router with health checking and fallback logic.

    Reads config["routing"] for:
        strategy:           RoutingStrategy value (default "free_first")
        allow_paid:         Whether to fall back to paid APIs (default False)
        preferred_provider: Override — always try this provider first
        fallback_order:     Custom ordering of provider names
        health_check_ttl:   Seconds to cache health check results (default 60)
    """

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self._routing_cfg = config.get("routing", {})
        self.strategy = RoutingStrategy(
            self._routing_cfg.get("strategy", "free_first")
        )
        self.allow_paid = self._routing_cfg.get("allow_paid", False)
        self.preferred_provider = self._routing_cfg.get("preferred_provider", "")
        self.fallback_order: list[str] = self._routing_cfg.get(
            "fallback_order", DEFAULT_FALLBACK_ORDER
        )
        self.health_check_ttl = self._routing_cfg.get("health_check_ttl", 60)

        # Ensure providers are registered
        register_all_providers()

        # Cached provider instances and health statuses
        self._instances: dict[str, BaseProvider] = {}
        self._statuses: dict[str, ProviderStatus] = {}
        self._last_route_provider: str = ""

    # ── Public API ────────────────────────────────────────────────────────

    async def route(
        self,
        messages: list[dict] | None = None,
        max_tokens: int = 1024,
    ) -> BaseProvider:
        """Pick the best available provider and return an instance.

        Tries providers in priority order based on the current strategy.
        Raises RuntimeError if no provider is available.
        """
        order = self._build_priority_order()

        for name in order:
            status = await self._check_provider(name)
            if not status.available:
                continue
            if not status.healthy:
                continue

            provider = self.get_provider(name)
            if provider is not None:
                self._last_route_provider = name
                logger.info(
                    "Routed to provider '%s' (strategy=%s, latency=%.0fms)",
                    name, self.strategy.value, status.latency_ms,
                )
                return provider

        # Nothing worked
        checked = ", ".join(order) if order else "(none)"
        raise RuntimeError(
            f"No available provider. Checked: {checked}. "
            f"Strategy: {self.strategy.value}, allow_paid: {self.allow_paid}"
        )

    def get_provider(self, name: str) -> BaseProvider | None:
        """Get or create a provider instance by name.

        Returns None if the provider cannot be instantiated (missing key, etc.).
        """
        # Normalize alias
        if name == "trio":
            name = "local"

        if name in self._instances:
            return self._instances[name]

        # Build provider-specific config
        provider_cfg = self._build_provider_config(name)
        if provider_cfg is None:
            return None

        try:
            # Map name to registered provider class name
            reg_name = name if name != "local" else "local"
            provider = ProviderRegistry.create(reg_name, provider_cfg)
            self._instances[name] = provider
            return provider
        except (ValueError, Exception) as exc:
            logger.warning("Failed to create provider '%s': %s", name, exc)
            return None

    async def available_providers(self) -> list[dict[str, Any]]:
        """List all providers with their current status.

        Returns a list of dicts with: name, available, healthy, is_local,
        is_free, latency_ms, error, models.
        """
        results = []
        for name in self._all_provider_names():
            status = await self._check_provider(name)
            results.append({
                "name": status.name,
                "available": status.available,
                "healthy": status.healthy,
                "is_local": status.is_local,
                "is_free": status.is_free,
                "has_api_key": status.has_api_key,
                "latency_ms": round(status.latency_ms, 1),
                "error": status.error,
                "models": status.models,
            })
        return results

    def estimate_cost(self, provider_name: str, tokens: int) -> dict[str, float]:
        """Estimate the cost of a request for a given provider.

        Returns {"input": $, "output": $, "total": $} in USD.
        """
        rates = COST_PER_MILLION_TOKENS.get(provider_name, {"input": 0.0, "output": 0.0})
        # Assume roughly 1:1 input:output ratio for estimation
        input_cost = (tokens / 1_000_000) * rates["input"]
        output_cost = (tokens / 1_000_000) * rates["output"]
        return {
            "input": round(input_cost, 6),
            "output": round(output_cost, 6),
            "total": round(input_cost + output_cost, 6),
        }

    @property
    def last_routed_provider(self) -> str:
        """Name of the provider selected by the most recent route() call."""
        return self._last_route_provider

    def update_config(self, routing_cfg: dict[str, Any]) -> None:
        """Update routing configuration at runtime."""
        self._routing_cfg.update(routing_cfg)

        if "strategy" in routing_cfg:
            try:
                self.strategy = RoutingStrategy(routing_cfg["strategy"])
            except ValueError:
                pass

        if "allow_paid" in routing_cfg:
            self.allow_paid = bool(routing_cfg["allow_paid"])

        if "preferred_provider" in routing_cfg:
            self.preferred_provider = routing_cfg["preferred_provider"]

        if "fallback_order" in routing_cfg:
            self.fallback_order = routing_cfg["fallback_order"]

        # Persist into parent config
        self.config.setdefault("routing", {}).update(routing_cfg)

        # Clear health cache so next route() re-checks
        self._statuses.clear()

    async def close(self) -> None:
        """Close all cached provider instances."""
        for provider in self._instances.values():
            try:
                await provider.close()
            except Exception:
                pass
        self._instances.clear()
        self._statuses.clear()

    # ── Priority ordering ─────────────────────────────────────────────────

    def _build_priority_order(self) -> list[str]:
        """Build the ordered list of providers to try based on strategy."""
        # If a preferred provider is set, always try it first
        preferred = []
        if self.preferred_provider:
            preferred = [self.preferred_provider]

        if self.strategy == RoutingStrategy.LOCAL_ONLY:
            candidates = [n for n in self.fallback_order if n in LOCAL_PROVIDERS or n == "ollama"]

        elif self.strategy == RoutingStrategy.FREE_FIRST:
            # local → ollama → free APIs → paid (if allowed)
            free = [n for n in self.fallback_order if n in FREE_PROVIDERS]
            paid = [n for n in self.fallback_order if n not in FREE_PROVIDERS] if self.allow_paid else []
            candidates = free + paid

        elif self.strategy == RoutingStrategy.BALANCED:
            # Interleave free and cheap paid providers by cost
            all_names = list(self.fallback_order)
            if not self.allow_paid:
                all_names = [n for n in all_names if n in FREE_PROVIDERS]
            candidates = all_names

        elif self.strategy == RoutingStrategy.QUALITY_FIRST:
            # Reverse: prefer paid (higher quality) first, then free
            if self.allow_paid:
                paid = [n for n in self.fallback_order if n not in FREE_PROVIDERS]
                free = [n for n in self.fallback_order if n in FREE_PROVIDERS]
                candidates = paid + free
            else:
                candidates = [n for n in self.fallback_order if n in FREE_PROVIDERS]

        else:
            candidates = list(self.fallback_order)

        # Deduplicate while preserving order, with preferred at front
        seen = set()
        result = []
        for name in preferred + candidates:
            if name not in seen:
                seen.add(name)
                result.append(name)
        return result

    # ── Health checking ───────────────────────────────────────────────────

    async def _check_provider(self, name: str) -> ProviderStatus:
        """Check if a provider is available and healthy (with caching)."""
        now = time.time()

        # Return cached result if fresh
        if name in self._statuses:
            cached = self._statuses[name]
            if now - cached.last_check < self.health_check_ttl:
                return cached

        status = ProviderStatus(
            name=name,
            is_local=name in LOCAL_PROVIDERS,
            is_free=name in FREE_PROVIDERS,
        )

        if name in ("local", "trio"):
            status = await self._check_local(status)
        elif name == "ollama":
            status = await self._check_ollama(status)
        else:
            status = await self._check_api_provider(name, status)

        status.last_check = now
        self._statuses[name] = status
        return status

    async def _check_local(self, status: ProviderStatus) -> ProviderStatus:
        """Check if local GGUF inference is available."""
        try:
            from trio.providers.local import _list_gguf_models
            models = _list_gguf_models()
            if models:
                status.available = True
                status.healthy = True
                status.models = models
                status.latency_ms = 0
            else:
                status.available = False
                status.error = "No GGUF models found in ~/.trio/models/ or project models/"
        except ImportError:
            status.available = False
            status.error = "llama-cpp-python not installed"
        except Exception as exc:
            status.available = False
            status.error = str(exc)
        return status

    async def _check_ollama(self, status: ProviderStatus) -> ProviderStatus:
        """Ping the Ollama server to check availability."""
        ollama_cfg = self.config.get("providers", {}).get("ollama", {})
        base_url = ollama_cfg.get("base_url", "http://localhost:11434")

        try:
            start = time.time()
            timeout = aiohttp.ClientTimeout(total=3)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(f"{base_url}/api/tags") as resp:
                    latency = (time.time() - start) * 1000
                    if resp.status == 200:
                        data = await resp.json()
                        models = [m["name"] for m in data.get("models", [])]
                        status.available = True
                        status.healthy = True
                        status.latency_ms = latency
                        status.models = models
                    else:
                        status.available = False
                        status.error = f"Ollama returned HTTP {resp.status}"
        except (aiohttp.ClientConnectorError, asyncio.TimeoutError):
            status.available = False
            status.error = "Ollama not running or not reachable"
        except Exception as exc:
            status.available = False
            status.error = str(exc)
        return status

    async def _check_api_provider(self, name: str, status: ProviderStatus) -> ProviderStatus:
        """Check if an API-based provider has credentials and is reachable."""
        from trio.providers.openai_compat import KNOWN_PROVIDERS as API_BASES

        provider_cfg = self.config.get("providers", {}).get(name, {})
        api_key = provider_cfg.get("apiKey", "") or provider_cfg.get("api_key", "")
        api_base = provider_cfg.get("apiBase", "") or API_BASES.get(name, "")

        # Check if API key exists
        if not api_key:
            # Check environment variables as fallback
            env_map = {
                "openai": "OPENAI_API_KEY",
                "anthropic": "ANTHROPIC_API_KEY",
                "groq": "GROQ_API_KEY",
                "gemini": "GEMINI_API_KEY",
                "openrouter": "OPENROUTER_API_KEY",
                "together": "TOGETHER_API_KEY",
                "deepseek": "DEEPSEEK_API_KEY",
            }
            import os
            env_var = env_map.get(name, "")
            if env_var:
                api_key = os.environ.get(env_var, "")

        if not api_key:
            status.available = False
            status.has_api_key = False
            status.error = f"No API key configured for {name}"
            return status

        status.has_api_key = True

        # Ping the models endpoint to verify connectivity
        if not api_base:
            status.available = False
            status.error = f"No API base URL for {name}"
            return status

        try:
            start = time.time()
            timeout = aiohttp.ClientTimeout(total=5)
            headers = {"Authorization": f"Bearer {api_key}"}
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                async with session.get(f"{api_base}/models") as resp:
                    latency = (time.time() - start) * 1000
                    if resp.status == 200:
                        try:
                            data = await resp.json()
                            models = [m.get("id", "") for m in data.get("data", [])][:10]
                            status.models = models
                        except Exception:
                            pass
                        status.available = True
                        status.healthy = True
                        status.latency_ms = latency
                    elif resp.status == 401:
                        status.available = False
                        status.error = f"Invalid API key for {name}"
                    else:
                        # Some providers don't have /models endpoint but still work
                        # Mark as available if we have a key
                        status.available = True
                        status.healthy = True
                        status.latency_ms = latency
        except (aiohttp.ClientConnectorError, asyncio.TimeoutError):
            # If we have a key but can't reach the server, mark unavailable
            status.available = False
            status.error = f"Cannot reach {name} API at {api_base}"
        except Exception as exc:
            status.available = False
            status.error = str(exc)

        return status

    # ── Helpers ────────────────────────────────────────────────────────────

    def _build_provider_config(self, name: str) -> dict[str, Any] | None:
        """Build the config dict needed to instantiate a provider."""
        import os
        from trio.providers.openai_compat import KNOWN_PROVIDERS as API_BASES

        providers_cfg = self.config.get("providers", {})

        if name in ("local", "trio"):
            cfg = dict(providers_cfg.get("local", providers_cfg.get("trio", {})))
            cfg.setdefault("default_model", "trio-max")
            return cfg

        if name == "ollama":
            cfg = dict(providers_cfg.get("ollama", {}))
            cfg.setdefault("base_url", "http://localhost:11434")
            cfg.setdefault("default_model", "llama3.1:8b")
            return cfg

        # API-based provider
        cfg = dict(providers_cfg.get(name, {}))

        # Resolve API key from config or environment
        api_key = cfg.get("apiKey", "") or cfg.get("api_key", "")
        if not api_key:
            env_map = {
                "openai": "OPENAI_API_KEY",
                "anthropic": "ANTHROPIC_API_KEY",
                "groq": "GROQ_API_KEY",
                "gemini": "GEMINI_API_KEY",
                "openrouter": "OPENROUTER_API_KEY",
                "together": "TOGETHER_API_KEY",
                "deepseek": "DEEPSEEK_API_KEY",
            }
            env_var = env_map.get(name, "")
            if env_var:
                api_key = os.environ.get(env_var, "")

        if not api_key:
            return None  # Cannot create without API key

        cfg["apiKey"] = api_key
        cfg["provider_name"] = name

        # Set API base URL
        if not cfg.get("apiBase"):
            cfg["apiBase"] = API_BASES.get(name, "")

        # Set default model if not configured
        default_models = {
            "openai": "gpt-4o",
            "anthropic": "claude-sonnet-4-20250514",
            "groq": "llama-3.3-70b-versatile",
            "gemini": "gemini-2.5-flash",
            "openrouter": "anthropic/claude-sonnet-4",
            "together": "meta-llama/Llama-3-70b",
            "deepseek": "deepseek-chat",
        }
        if not cfg.get("default_model"):
            cfg["default_model"] = default_models.get(name, "")

        return cfg

    def _all_provider_names(self) -> list[str]:
        """Return all known provider names in a sensible order."""
        base = list(DEFAULT_FALLBACK_ORDER)
        # Add any extra providers from config that aren't in the default list
        for name in self.config.get("providers", {}):
            if name not in base and name != "trio":
                base.append(name)
        return base

    def get_routing_info(self) -> dict[str, Any]:
        """Return current routing configuration as a dict (for API responses)."""
        return {
            "strategy": self.strategy.value,
            "allow_paid": self.allow_paid,
            "preferred_provider": self.preferred_provider,
            "fallback_order": self.fallback_order,
            "health_check_ttl": self.health_check_ttl,
            "last_routed_provider": self._last_route_provider,
        }
