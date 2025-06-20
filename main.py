# main.py — PF2e Discord Bot (syntax‑clean, ready to deploy)
# ---------------------------------------------------------------------------
# Key points:
#   • Shared aiohttp session (created in setup_hook, closed in bot.close)
#   • No privileged intents needed
#   • 2 000‑char splitter for Discord message limit
#   • Clickable AoN URL under item name
# ---------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
import time
from html import unescape
from typing import Optional, List

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

# ── Logging ─────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("pf2e-bot")

# ── Configuration ─────────────────────────────────────────────
TOKEN = os.getenv("DiscordOracle") or os.getenv("DISCORD_TOKEN")
if not TOKEN:
    logger.error("Discord token missing (DiscordOracle / DISCORD_TOKEN)")
    sys.exit(1)

AON_API_BASE = "https://elasticsearch.aonprd.com/aon/_search"
AON_WEB_BASE = "https://2e.aonprd.com/"

SEARCH_CATEGORIES = [
    "Equipment", "Spell", "Feat", "Class", "Ancestry", "Background",
    "Monster", "Hazard", "Rule", "Condition", "Trait", "Action",
]

# ── Global HTTP session placeholder ───────────────────────────
_http_session: aiohttp.ClientSession | None = None

# ── TTL Cache ─────────────────────────────────────────────────
class SearchCache:
    def __init__(self, ttl: int = 300):
        self.ttl = ttl
        self._cache: dict[str, tuple[object, float]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str):
        async with self._lock:
            entry = self._cache.get(key)
            if not entry:
                return None
            value, ts = entry
            if time.time() - ts < self.ttl:
                return value
            del self._cache[key]
            return None

    async def set(self, key: str, value):
        async with self._lock:
            self._cache[key] = (value, time.time())

search_cache = SearchCache()

# ── Regular expressions ───────────────────────────────────────
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
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

# ── Utility helpers ───────────────────────────────────────────

def clean_text(text: str | None) -> str:
    if not text:
        return ""
    text = TAG_RE.sub("", text)
    return WS_RE.sub(" ", unescape(text)).strip()


async def search_aon_api(query: str, *, result_limit: int = 5, category_filter: str | None = None):
    """Search the AoN ES endpoint with simple caching."""
    cache_key = f"{query}:{result_limit}:{category_filter}"
    if (cached := await search_cache.get(cache_key)) is not None:
        return cached

    if _http_session is None:
        raise RuntimeError("HTTP session not initialised yet")

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
        async with _http_session.post(AON_API_BASE, json=body, headers={"User-Agent": "PF2E Discord Bot"}) as resp:
            resp.raise_for_status()
            data = await resp.json()
    except Exception as exc:
        logger.error("AoN API error: %s", exc)
        return []

    results: list[dict] = []
    for hit in data.get("hits", {}).get("hits", []):
        src = hit.get("_source", {})
        url = src.get("url", "")
        if url and not url.startswith("http"):
            url = AON_WEB_BASE + url.lstrip("/")
        results.append({
            "name": src.get("name", "Unknown"),
            "type": src.get("type", "Unknown"),
            "url": url,
            "text": src.get("text", ""),
            "level": src.get("level"),
            "price": src.get("price"),
            "category": src.get("category"),
            "source": src.get("source"),
            "rarity": src.get("rarity"),
        })

    await search_cache.set(cache_key, results)
    return results


# ── Parsing helpers ───────────────────────────────────────────

def parse_traits(text: str) -> List[str]:
    traits: List[str] = []
    seen: set[str] = set()
    for m in TRAIT_RE.finditer(text):
        token = m.group(0)
        if token.lower().startswith("versatile"):
            token = f"Versatile {token.split()[-1].upper()}"
        else:
            token = token.title()
        if token not in seen:
            seen.add(token)
            traits.append(token)
    return traits


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

# Critical specialisation effects (abbreviated)
CRIT_EFFECTS = {
    "sword": "Target is **flat-footed** until the start of your next turn.",
    "axe": "Swipe an adjacent creature …",
    "bow": "Pin the target; it becomes **immobilised** (DC 10 Athletics to escape).",
    "club": "Knock the target 10 ft away.",
    "flail": "The target is knocked **prone**.",
    "hammer": "The target is knocked **prone**.",
    "knife": "Target takes 1d6 persistent bleed damage.",
    "polearm": "Move the target 5 ft in a direction of your choice.",
    "spear": "Target takes –2 circumstance penalty to damage for 1 round.",
}


def crit_effect(group: str | None) -> str:
    return CRIT_EFFECTS.get((group or "").lower(), "No specific effect for this weapon group.")

# ── Formatting helpers ───────────────────────────────────────

def plural(word: str) -> str:
    return word if word.endswith("s") else word + "s"


def first_after(label: str, text: str) -> Optional[str]:
    pat = re.compile(fr"{label}[^.]*?([A-Z][^.]+)", re.I)
    if (m := pat.search(text)):
        return WS_RE.sub(" ", m.group(1).strip())
    return None


def main_desc(text: str) -> str:
    sents = [s.strip() for s in text.split(".") if len(s.strip()) > 15]
    keep = [s for s in sents if not any(k in s.lower() for k in ("source", "favored weapon", "specific magic", "price", "bulk", "hands", "damage", "category"))]
    return (". ".join(keep[:2]) + ".") if keep else "A martial weapon used in combat."


def format_result(res: dict) -> str:
    raw = clean_text(res.get("text"))
    traits = parse_traits(raw)
    stats = parse_weapon_stats(raw)
    type_ = (res.get("type") or "").lower()
    category = (res.get("category") or "").lower()

    lines: List[str] = ["****Item****"]
    name_line = res["name"]
    if res.get("rarity") and res["rarity"].lower() != "common":
        name_line += f" ({res['rarity']})"
    lines.append(f"**{name_line}**")
    lines.append("".join(f"［ {t} ］" for t in traits) or "None")

    # Equipment/Weapon
    if type_ == "weapon" or category == "weapon":
        lines.append(f"**Price** {res.get('price', 'Unknown')}")
        lines.append(f"**Bulk** {stats.get('bulk', 'Unknown')}; **Hands** {stats.get('hands', '1')}")
        lines.append(f"**Damage** {stats.get('damage', 'Unknown')}")
        lines.append(f"**Category** {res.get('category', 'weapon')}; **Group** {stats.get('group', 'unknown')}")
        lines.append("⎯" * 30)
        lines.append(main_desc(raw))
        lines.append("")
        lines.append(f"📘 **Source:** {res.get('source', 'Unknown')}")
        lines.append("")
        lines.append("****Favored Weapon of****")
        lines.append(first_after("favored weapon", raw) or "None")
        lines.append("")
        group_title = stats.get("group", "Unknown").title()
        lines.append(f"****Critical Specialization Effect ({group_title} Group):****")
        lines.append(crit_effect(stats.get("group")))
        lines.append("")
        lines.append(f"****Specific Magic {plural(res['name'])}:****")
        lines.append(first_after("specific magic", raw) or "None")
    # Spell
    elif type_ == "spell":
        lines.append(f"**Level** {res.get('level', 'Unknown')}")
        lines.append(f"**Source** {res.get('source', 'Unknown')}")
        lines.append("⎯" * 30)
        lines.append(main_desc(raw))
    # Feat
    elif type_ == "feat":
        lines.append(f"**Level** {res.get('level', 'Unknown')}")
        lines.append(f"**Source** {res.get('source', 'Unknown')}")
        lines.append("⎯" * 30)
        lines.append(main_desc(raw))
    # Class, Ancestry, Background, Monster, etc.
    else:
        if res.get("level"):
            lines.append(f"**Level** {res.get('level')}")
        if res.get("source"):
            lines.append(f"**Source** {res.get('source')}")
        lines.append("⎯" * 30)
        lines.append(main_desc(raw))
    lines.append("")
    lines.append("🔗 Data from Archives of Nethys")
    if res.get("url"):
        lines.append(res["url"])
    return "\n".join(lines)

# ── Discord helpers ──────────────────────────────────────────

def chunk_send(inter: discord.Interaction, text: str):
    """Yield chunks <= 1900 chars (keeping code healthy)."""
    for i in range(0, len(text), 1900):
        yield text[i:i + 1900]

# ── Autocomplete data ────────────────────────────────────────
POPULAR_TERMS = [
    "longsword", "healing potion", "fireball", "leather armor", "shield",
    "dagger", "shortbow", "chain mail", "rapier", "meteor hammer",
]

async def ac_category(_: discord.Interaction, current: str):
    cats = ["All"] + SEARCH_CATEGORIES
    return [app_commands.Choice(name=c, value=c) for c in cats if current.lower() in c.lower()][:25]

async def ac_query(_: discord.Interaction, current: str):
    if len(current) < 2:
        return []
    return [app_commands.Choice(name=t.title(), value=t) for t in POPULAR_TERMS if current.lower() in t][:25]

# ── Bot class ────────────────────────────────────────────────
class PF2eBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix=commands.when_mentioned, intents=discord.Intents.default())

    async def setup_hook(self):
        global _http_session
        _http_session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
        synced = await self.tree.sync()
        logger.info("Synced %d commands", len(synced))

    async def close(self):
        global _http_session
        if _http_session and not _http_session.closed:
            await _http_session.close()
        await super().close()

bot = PF2eBot()

# ── /search command ─────────────────────────────────────────
@bot.tree.command(name="search", description="Search Archives of Nethys for PF2e content")
@app_commands.describe(query="Search term", category="Optional category filter")
@app_commands.autocomplete(query=ac_query, category=ac_category)
async def cmd_search(inter: discord.Interaction, query: str, category: Optional[str] = None):
    await interaction_response_defer_safe(inter)
    try:
        results = await search_aon_api(query, category_filter=category)
    except Exception as exc:
        logger.error("search error: %s", exc)
        await safe_followup(inter, "Error while searching. Please try again later.")
        return

    if not results:
        await safe_followup(inter, f"**No results found for `{query}`**")
        return

    text = format_result(results[0])
    for chunk in chunk_send(inter, text):
        await safe_followup(inter, chunk)

# safe helpers for follow‑ups and defer
async def interaction_response_defer_safe(inter: discord.Interaction):
    if not inter.response.is_done():
        try:
            await inter.response.defer()
        except Exception:
            pass

async def safe_followup(inter: discord.Interaction, content: str):
    target = inter.followup if inter.response.is_done() else inter.response
    try:
        await target.send(content)
    except Exception as err:
        logger.error("follow‑up failed: %s", err)

# ── /help command ───────────────────────────────────────────
@bot.tree.command(name="help", description="Show help information")
async def cmd_help(inter: discord.Interaction):
    msg = (
        "**PF2e Bot Help**\n\n"
        "• `/search <term>` — search Archives of Nethys. Optional `category` arg narrows the type.\n"
        "  Use tab‑completion for quick suggestions."
    )
    if not inter.response.is_done():
        await inter.response.send_message(msg, ephemeral=True)
    else:
        await inter.followup.send(msg, ephemeral=True)

# ── Run bot ─────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        bot.run(TOKEN)
    except discord.errors.LoginFailure:
        logger.error("Invalid token — check DISCORD_TOKEN/DiscordOracle.")

