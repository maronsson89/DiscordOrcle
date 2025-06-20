# main.py – Simple PF2e Discord Bot with Slash Commands (Refactored + clickable links)
# ---------------------------------------------------------------
# Key fixes
#   • Single shared aiohttp session (no per-request overhead)
#   • Removed unnecessary privileged intent
#   • Robust 2 000-character message splitting
#   • Graceful pluralisation & None‑safe helpers
#   • Item URL now shown as a clickable link in the output
#   • Minor cleanup & clearer token handling
# ---------------------------------------------------------------

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import time
from html import unescape
from typing import List, Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands


# ── Logging ────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("pf2e-bot")


# ── Configuration ─────────────────────────────────────────────
TOKEN = os.getenv("DiscordOracle") or os.getenv("DISCORD_TOKEN")
if not TOKEN:
    logger.error("Discord token not provided (env vars DiscordOracle / DISCORD_TOKEN). Exiting …")
    sys.exit(1)

AON_API_BASE = "https://elasticsearch.aonprd.com/aon/_search"
AON_WEB_BASE = "https://2e.aonprd.com/"

SEARCH_CATEGORIES = [
    "Equipment", "Spell", "Feat", "Class", "Ancestry", "Background",
    "Monster", "Hazard", "Rule", "Condition", "Trait", "Action",
]


# ── Globals ───────────────────────────────────────────────────
_http_session: aiohttp.ClientSession | None = None  # initialised in setup_hook()


# ── Simple in‑memory cache ────────────────────────────────────
class SearchCache:
    """Tiny TTL cache with coroutine‑safe access."""

    def __init__(self, ttl_seconds: int = 300):
        self.cache: dict[str, tuple[object, float]] = {}
        self.ttl = ttl_seconds
        self._lock = asyncio.Lock()

    async def get(self, key: str):
        async with self._lock:
            if key not in self.cache:
                return None
            value, ts = self.cache[key]
            if time.time() - ts < self.ttl:
                return value
            del self.cache[key]
            return None

    async def set(self, key: str, value):
        async with self._lock:
            self.cache[key] = (value, time.time())


search_cache = SearchCache()


# ── Utility helpers ───────────────────────────────────────────
TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")


def clean_text(text: str | None) -> str:
    if not text:
        return ""
    text = TAG_RE.sub("", text)
    text = unescape(text)
    return WHITESPACE_RE.sub(" ", text).strip()


async def search_aon_api(query: str, *, result_limit: int = 5, category_filter: str | None = None):
    """Query the (unofficial) Archives of Nethys ES API with caching."""

    cache_key = f"{query}:{result_limit}:{category_filter}"
    if (cached := await search_cache.get(cache_key)) is not None:
        logger.debug("cache hit for %s", query)
        return cached

    if _http_session is None:
        raise RuntimeError("HTTP session not initialised")

    bool_query: dict = {
        "should": [
            {
                "multi_match": {
                    "query": query,
                    "fields": ["name^3", "text^2", "trait_raw^2"],
                    "type": "best_fields",
                    "fuzziness": "AUTO",
                }
            },
            {"wildcard": {"name.keyword": f"*{query.lower()}*"}},
        ],
        "minimum_should_match": 1,
    }
    if category_filter and category_filter != "All":
        bool_query.setdefault("filter", []).append({"term": {"type.keyword": category_filter}})

    payload = {
        "query": {"bool": bool_query},
        "size": result_limit,
        "_source": [
            "name",
            "type",
            "url",
            "text",
            "level",
            "price",
            "category",
            "source",
            "rarity",
        ],
        "sort": [{"_score": {"order": "desc"}}, {"name.keyword": {"order": "asc"}}],
    }

    try:
        async with _http_session.post(
            AON_API_BASE,
            json=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "PF2E Discord Bot (aiohttp)",
                "Accept": "application/json",
                "Referer": "https://2e.aonprd.com/",
            },
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
    except aiohttp.ClientResponseError as e:
        logger.error("AON API error (%s): %s", e.status, e.message)
        return []
    except Exception as e:
        logger.error("AON API request failed: %s", e)
        return []

    results: list[dict] = []
    for hit in data.get("hits", {}).get("hits", []):
        src = hit.get("_source", {})
        url = src.get("url", "")
        if url and not url.startswith("http"):
            url = AON_WEB_BASE + url.lstrip("/")
        results.append(
            {
                "name": src.get("name", "Unknown"),
                "type": src.get("type", "Unknown"),
                "url": url,
                "text": src.get("text", ""),
                "level": src.get("level"),
                "price": src.get("price"),
                "category": src.get("category"),
                "source": src.get("source"),
                "rarity": src.get("rarity"),
                "score": hit.get("_score"),
            }
        )

    await search_cache.set(cache_key, results)
    return results


# ── Regex helpers for weapon parsing ──────────────────────────
DAMAGE_RES = [
    re.compile(r"(\d+d\d+(?:\+\d+)?)\s+(slashing|piercing|bludgeoning|s|p|b)\b", re.I),
    re.compile(r"damage\s+(\d+d\d+(?:\+\d+)?)(?:\s*(\w+))?", re.I),
]
BULK_RES = [re.compile(p, re.I) for p in (r"bulk\s+([0-9]+|L|-)\b", r"bulk: ?([0-9]+|L|-)")]
HANDS_RES = [re.compile(p, re.I) for p in (r"hands?\s+(\d+)\b", r"hands?: ?(\d+)")]
GROUP_RES = [re.compile(p, re.I) for p in (r"group\s+(\w+)\b", r"weapon\s+group: ?(\w+)")]
TRAIT_RE = re.compile(
    r"\b("  # capture
    r"backswing|disarm|reach|trip|finesse|agile|deadly|fatal|parry|sweep|forceful|shove|twin|monk|unarmed|free-hand|grapple|nonlethal|propulsive|volley|ranged|thrown"  # simple traits
    r"|versatile\s+[a-z]"  # versatile X
    r")\b",
    re.I,
)


# ── Parsing functions ────────────────────────────────────────

def parse_traits(text: str) -> list[str]:
    traits: list[str] = []
    for m in TRAIT_RE.finditer(text):
        token = m.group(0)
        if token.lower().startswith("versatile"):
            dmg = token.split()[-1].upper()
            traits.append(f"Versatile {dmg}")
        else:
            traits.append(token.title())
    return list(dict.fromkeys(traits))  # preserve order, remove dups


def parse_weapon_stats(text: str) -> dict[str
