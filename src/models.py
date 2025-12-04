"""Model configuration and loading from OpenRouter API."""

import re

import httpx

OPENROUTER_MODELS_URL = 'https://openrouter.ai/api/v1/models'
CLAUDE_TIERS = ('haiku', 'sonnet', 'opus')

_cached_models: dict | None = None
_claude_aliases: dict[str, str] | None = None


def _extract_claude_tier(model_id: str) -> str | None:
    """Extract Claude tier (haiku/sonnet/opus) from a model ID.
    """
    model_id_lower = model_id.lower()
    for tier in CLAUDE_TIERS:
        if tier in model_id_lower:
            return tier
    return None


def _build_claude_aliases(models_data: dict) -> dict[str, str]:
    """Build alias mapping from fetched models, selecting newest per tier.
    """
    tier_candidates: dict[str, list[tuple[int, str]]] = {
        tier: [] for tier in CLAUDE_TIERS
    }

    for model in models_data.get('data', []):
        model_id = model.get('id', '')
        if not model_id.startswith('anthropic/claude'):
            continue

        tier = _extract_claude_tier(model_id)
        if tier and not re.search(r':(free|beta|extended)', model_id):
            created = model.get('created', 0)
            tier_candidates[tier].append((created, model_id))

    aliases: dict[str, str] = {}
    for tier, candidates in tier_candidates.items():
        if candidates:
            candidates.sort(reverse=True)
            aliases[tier] = candidates[0][1]

    return aliases


async def fetch_models() -> dict:
    """Fetch models from OpenRouter API and build Claude aliases.
    """
    global _cached_models, _claude_aliases
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(OPENROUTER_MODELS_URL)
        response.raise_for_status()
        _cached_models = response.json()
    _claude_aliases = _build_claude_aliases(_cached_models)
    return _cached_models


async def get_models() -> dict:
    """Get models (from memory cache or fetch from API).
    """
    if _cached_models is None:
        return await fetch_models()
    return _cached_models


def get_claude_aliases() -> dict[str, str]:
    """Get the dynamically-built Claude alias mapping (sync, uses cache).
    """
    if _claude_aliases is None:
        return {}
    return _claude_aliases


def get_model_ids() -> set[str]:
    """Get set of valid OpenRouter model IDs (sync, uses cache only).
    """
    if _cached_models is None:
        return set()
    return {m['id'] for m in _cached_models.get('data', [])}


def map_model(anthropic_model: str) -> str:
    """Map Anthropic model names to OpenRouter model IDs.

    Handles three cases: OpenRouter IDs (contain '/'), Claude aliases
    (haiku/sonnet/opus mapped to newest versions), and passthrough for
    unrecognized models.
    """
    if '/' in anthropic_model:
        return anthropic_model

    model_lower = anthropic_model.lower()
    aliases = get_claude_aliases()
    for tier in CLAUDE_TIERS:
        if tier in model_lower and tier in aliases:
            return aliases[tier]

    return anthropic_model
