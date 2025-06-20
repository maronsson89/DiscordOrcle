# main.py – Simple PF2e Discord Bot with Slash Commands (Refactored + clickable links)
# -------------------------------------------------------------------
# Highlights
#   • Shared aiohttp session for speed
#   • No privileged intents required
#   • Robust 2 000‑character splitter
#   • Clickable URL line after item name
#   • Complete, syntactically‑valid source (fixes unclosed '[' error)
# -------------------------------------------------------------------

from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
import time
from html import unescape
from typing import Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

# ── Logging ──────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("pf2e-bot")

# ── Configuration ───────────────────────────────────────────────
TOKEN = os.getenv("DiscordOracle") or os.getenv("DISCORD_TOKEN")
if not TOKEN:
    logger.error("Discord token not provided (DiscordOracle / DISCORD_TOKEN). Exiting …")
    sys.exit(1)

AON_API_BASE = "https://elasticsearch.aonprd.com/aon/_search"
AON_WEB_BASE = "https://2e.aonprd.com/"

SEARCH_CATEGORIES = [
    "Equipment", "Spell", "Feat", "Class", "Ancestry", "Background",
    "Monster", "Hazard", "Rule", "Condition", "Trait", "Action",
]

# ── Globals ─────────────────────────────────────────────────────
_http_session: aiohttp.ClientSession | None = None

# ── Simple in‑memory TTL cache ─────────────────────────────────
class SearchCache:
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

# ── Utility regexes ────────────────────────────────────────────
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")

# ── Helper functions ───────────────────────────────────────────

def clean_text(text: str | None) -> str:
    if not text:
        return ""
    text = TAG_RE.sub("", text)
    text = unescape(text)
    return WS_RE.sub(" ", text).strip()

async def search_aon_api(query: str, *, result_limit: int = 5, category_filter: str | None = None):
    cache_key = f"{query}:{result_limit}:{category_filter}"
    if (cached := await search_cache.get(cache_key)) is not None:
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

    body = {
        "query": {"bool": bool_query},
        "size": result_limit,
        "_source": ["name", "type", "url", "text", "level", "price", "category", "source", "rarity"],
        "sort": [{"_score": {"order": "desc"}}, {"name.keyword": {"order": "asc"}}],
    }

    try:
        async with _http_session.post(
            AON_API_BASE,
            json=body,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "PF2E Discord Bot",
                "Referer": "https://2e.aonprd.com/",
            },
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
    except Exception as exc:
        logger.error("AON API error: %s", exc)
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

# ── Regex helpers for parsing ─────────────────────────────────
DMG_RE = [
    re.compile(r"(\d+d\d+(?:\+\d+)?)\s+(slashing|piercing|bludgeoning|s|p|b)\b", re.I),
    re.compile(r"damage\s+(\d+d\d+(?:\+\d+)?)(?:\s*(\w+))?", re.I),
]
BULK_RE = [re.compile(p, re.I) for p in (r"bulk\s+([0-9]+|L|-)", r"bulk: ?([0-9]+|L|-)")]
HANDS_RE = [re.compile(p, re.I) for p in (r"hands?\s+(\d+)", r"hands?: ?(\d+)")]
GROUP_RE = [re.compile(p, re.I) for p in (r"group\s+(\w+)", r"weapon\s+group: ?(\w+)")]
TRAIT_RE = re.compile(
    r"\b(backswing|disarm|reach|trip|finesse|agile|deadly|fatal|parry|sweep|forceful|shove|twin|monk|unarmed|free-hand|grapple|nonlethal|propulsive|volley|ranged|thrown|versatile\s+[a-z])\b",
    re.I,
)

# ── Parsing helpers ───────────────────────────────────────────

def parse_traits(text: str) -> list[str]:
    seen = {}
    for m in TRAIT_RE.finditer(text):
        token = m.group(0)
        if token.lower().startswith("versatile"):
            val = f"Versatile {token.split()[-1].upper()}"
        else:
            val = token.title()
        seen[val] = None
    return list(seen)


def parse_weapon_stats(text: str) -> dict[str, str]:
    stats: dict[str, str] = {}
    # damage
    for rex in DMG_RE:
        if (m := rex.search(text)):
            die, typ = m.groups(default="")
            typ = typ.lower()
            typ = {"s": "slashing", "p": "piercing", "b": "bludgeoning"}.get(typ, typ or "slashing")
            stats["damage"] = f"{die} {typ}"
            break
    # bulk
    for rex in BULK_RE:
        if (m := rex.search(text)):
            stats["bulk"] = m.group(1)
            break
    # hands
    for rex in HANDS_RE:
        if (m := rex.search(text)):
            stats["hands"] = m.group(1)
            break
    if "hands" not in stats:
        stats["hands"] = "2" if "two-hand" in text.lower() else "1"
    # group
    for rex in GROUP_RE:
        if (m := rex.search(text)):
            stats["group"] = m.group(1).lower()
            break
    return stats

# Critical‑specialisation lookup table
CRIT = {
    "sword": "Target becomes **flat‑footed** until start of your next turn.",
    "axe": "Choose a second creature adjacent … (Core Rulebook).",
    "bow": "You pin the target to a surface, immobilising it (DC 10 Athletics to remove).",
    "club": "You knock the target 10 ft away (forced movement).",
    "flail": "The target is knocked **prone**.",
    "hammer": "The target is knocked **prone**.",
    "knife": "Target takes 1d6 persistent bleed damage.",
    "polearm": "Move the target 5 ft in a direction of your choice.",
    "spear": "Target takes –2 circumstance penalty to damage for 1 round.",
}

def crit_effect(group: str | None) -> str:
    return CRIT.get((group or "").lower(), "No specific effect for this weapon group.")

# ── Formatter ────────────────────────────────────────────────

def first_after(label: str, text: str) -> str | None:
    pat = re.compile(fr"{label}[^.]*?([A-Z][^.]+)", re.I)
    if (m := pat.search(text)):
        return WS_RE.sub(" ", m.group(1).strip())
    return None

def plural(word: str) -> str:
    return word if word.endswith("s") else word + "s"


def main_description(text: str) -> str:
    sents = [s.strip() for s in text.split(".") if len(s.strip()) > 15]
    filt = [s for s in sents if not any(k in s.lower() for k in ("source", "favored weapon", "specific magic", "price", "bulk", "hands", "damage", "category"))]
    return (". ".join(filt[:2]) + ".") if filt else "A martial weapon used in combat."


def format_result(res: dict) -> str:
    raw = clean_text(res.get("text"))
    traits = parse_traits(raw)
    stats = parse_weapon_stats(raw)

    lines: list[str] = ["****Item****"]
    name_line = res["name"] + (f" ({res['rarity']})" if res.get("rarity") and res["rarity"].lower() != "common" else "")
    lines.append(f"**{name_line}**")
    if res.get("url"):
        lines.append(f"<{res['url']}>")  # clickable link
    lines.append("".join(f"［ {t} ］" for t
