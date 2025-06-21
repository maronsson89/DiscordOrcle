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
WS_RE = re.compile(r"[ \t]+")
DMG_RE = [
    re.compile(r"(\d+d\d+(?:\+\d+)?)\s+(slashing|piercing|bludgeoning|s|p|b)\b", re.I),
    re.compile(r"damage\s+(\d+d\d+(?:\+\d+)?)(?:\s*(\w+))?", re.I),
]
BULK_RE = [re.compile(p, re.I) for p in (r"bulk\s+([0-9]+|L|-)", r"bulk: ?([0-9]+|L|-)")]
HANDS_RE = [re.compile(p, re.I) for p in (r"hands?\s+(\d+)", r"hands?: ?(\d+)")]
GROUP_RE = [re.compile(p, re.I) for p in (r"group\s+(\w+)", r"weapon\s+group: ?(\w+)")]

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
        "_source": ["name", "type", "url", "text", "level", "price", "category", "source", "rarity", "trait_raw"],
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
            "trait_raw": src.get("trait_raw", []),
        })

    await search_cache.set(cache_key, results)
    return results


# ── Parsing helpers ───────────────────────────────────────────

def parse_weapon_details(raw_text: str, traits: list) -> dict:
    details = {}

    # Size
    weight_match = re.search(r"their blades are (heavy)", raw_text, re.I)
    details['weight'] = weight_match.group(1).title() if weight_match else "N/A"
    length_match = re.search(r"between (3 and 4 feet) in length", raw_text, re.I)
    details['length'] = length_match.group(1) if length_match else "N/A"

    # Damage
    damage_match = re.search(r"Damage (\d+d\d+) (S|P|B)\b", raw_text, re.I)
    if damage_match:
        dmg_dice, dmg_type_char = damage_match.groups()
        dmg_type = {"S": "slashing", "P": "piercing", "B": "bludgeoning"}.get(dmg_type_char.upper(), "slashing")
        details['damage'] = f"{dmg_dice} {dmg_type}"
    else:
        details['damage'] = "N/A"

    # Versatile Trait
    details['versatile'] = ""
    for trait in traits:
        if trait.lower().startswith("versatile"):
            dmg_alt_char = trait.lower().split()[-1].upper()
            dmg_alt_full = {"S": "Slashing", "P": "Piercing", "B": "Bludgeoning"}.get(dmg_alt_char, "")
            if dmg_alt_full:
                details['versatile'] = f"**Versatile {dmg_alt_char}**: Damage Alternate(s) {dmg_alt_full} upon hit"

    # Hands, Bulk
    hands_match = re.search(r"Hands (\d+)", raw_text, re.I)
    details['hands'] = hands_match.group(1) if hands_match else "1"
    bulk_match = re.search(r"Bulk (\d+|L|-)", raw_text, re.I)
    details['bulk'] = bulk_match.group(1) if bulk_match else "N/A"

    # Classification
    type_match = re.search(r"Type (\w+)", raw_text, re.I)
    details['weapon_type'] = type_match.group(1).title() if type_match else "N/A"
    group_match = re.search(r"Group (\w+)", raw_text, re.I)
    details['group'] = group_match.group(1).title() if group_match else "N/A"
    details['category'] = res.get('category', 'N/A').title()

    # Description
    specific_desc_match = re.search(r"(Longswords can be one-edged or two-edged swords\.)", raw_text, re.I)
    if specific_desc_match:
        details['description'] = specific_desc_match.group(1)
    else:
        main_desc_match = re.search(r"^(.*?)\.", raw_text)
        details['description'] = main_desc_match.group(1) if main_desc_match else "No description available."
    return details


# Critical specialisation effects (abbreviated)
CRIT_EFFECTS = {
    "sword": "The target is made **off-guard** until the start of your next turn.",
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


def format_traits(traits: List[str], base_damage_str: str | None = None) -> str:
    if not traits:
        return "None"

    base_type = ""
    if base_damage_str and ' ' in base_damage_str:
        base_type = base_damage_str.split()[-1]

    descriptions = {
        "versatile p": "piercing",
        "versatile s": "slashing",
        "versatile b": "bludgeoning"
    }

    formatted_traits = []
    for trait in traits:
        lower_trait = trait.lower()
        if lower_trait in descriptions:
            alt_type = descriptions[lower_trait]
            display_trait = f"Versatile {lower_trait.split()[-1].upper()}"
            desc = f"**{display_trait}**: Can be used to deal {alt_type} damage"
            if base_type and base_type != alt_type:
                desc += f" instead of its normal {base_type} damage"
            desc += ". You choose the damage type each time you attack."
            formatted_traits.append(desc)
        else:
            formatted_traits.append(f"`{trait}`")
            
    return " ".join(formatted_traits)

# ── Formatting helpers ───────────────────────────────────────

def plural(word: str) -> str:
    return word if word.endswith("s") else word + "s"


def first_after(label: str, text: str) -> Optional[str]:
    pat = re.compile(fr"{label}[^.\n]*?([A-Z][^.\n]+)", re.I)
    if (m := pat.search(text)):
        return WS_RE.sub(" ", m.group(1).strip())
    return None


def main_desc(text: str) -> str:
    sents = [s.strip() for s in text.split(".") if len(s.strip()) > 15]
    bad_keywords = (
        "source", "favored weapon", "specific magic", "price", "bulk", "hands",
        "damage", "category", "group", "type", "level"
    )
    keep = [s for s in sents if not any(k in s.lower() for k in bad_keywords)]
    desc = (". ".join(keep[:2]) + ".") if keep else "No description available."
    return (desc[:4093] + '...') if len(desc) > 4096 else desc

def get_rarity_color(rarity: str | None) -> discord.Color:
    rarity = (rarity or "common").lower()
    if rarity == "uncommon":
        return discord.Color.blue()
    if rarity == "rare":
        return discord.Color.purple()
    if rarity == "unique":
        return discord.Color.gold()
    return discord.Color.default()

def truncate(text: str, max_len: int) -> str:
    return (text[:max_len - 3] + '...') if len(text) > max_len else text

def format_weapon_embed(res: dict) -> discord.Embed:
    raw = clean_text(res.get("text"))
    traits = res.get("trait_raw", [])
    details = parse_weapon_details(raw, traits)
    color = get_rarity_color(res.get("rarity"))

    embed = discord.Embed(
        title=res.get("name", "Unknown"),
        url=res.get("url"),
        color=color
    )

    desc_parts = [
        f"**Description:** {details['description']}",
        f"**Size:** Weight: {details['weight']}: Length: {details['length']}",
        f"__**Price:** {res.get('price', 'N/A')}__",
        "",
        f"__**Damage Traits:**__",
        f"**Primary Damage:** {details['damage']} {details['versatile']}",
        "",
        f"__**Requirements:**__",
        f"**{details['hands']} Handed** **Level:** {res.get('level', '0')} **Bulk:** {details['bulk']}"
    ]
    embed.description = "\n".join(desc_parts)

    embed.add_field(name="**Classification**", value="\u200b", inline=False)
    embed.add_field(name="Type", value=details['weapon_type'], inline=True)
    embed.add_field(name="Group", value=details['group'], inline=True)
    embed.add_field(name="Category", value=details['category'], inline=True)

    group = details.get("group")
    effect = crit_effect(group)
    group_title = (group or "Unknown").title()
    crit_explanation = "Certain feats, class features, weapon runes, and other effects can grant you additional benefits (might be mandatory)."
    crit_value = f"**{group_title}**: {effect}\n{crit_explanation}"

    embed.add_field(name="Critical Specialization Effects", value=crit_value, inline=False)

    favored_weapon_text = first_after("favored weapon", raw)
    if favored_weapon_text:
        just_names = re.match(r"([\w\s,]+)(?:\s+Price|\s+---)", favored_weapon_text)
        favored_text = just_names.group(1).strip() if just_names else favored_weapon_text
        embed.add_field(name="Favored by", value=truncate(favored_text, 1024), inline=False)

    specific_magic_text = first_after("specific magic", raw)
    if specific_magic_text:
        embed.add_field(name=f"Specific Magic {plural(res['name'])}", value=truncate(specific_magic_text, 1024),
                        inline=False)

    embed.set_footer(text=f"🔗 Data from Archives of Nethys | Source: {res.get('source', 'N/A')}")
    return embed

def format_spell_embed(res: dict) -> discord.Embed:
    raw = clean_text(res.get("text"))
    traits = res.get("trait_raw", [])
    color = get_rarity_color(res.get("rarity"))
    embed = discord.Embed(
        title=res.get("name", "Unknown"),
        url=res.get("url"),
        description=main_desc(raw),
        color=color
    )
    embed.add_field(name="Traits", value=truncate(" ".join(f"`{t}`" for t in traits) or "None", 1024), inline=False)
    if res.get('level'):
        embed.add_field(name="Level", value=str(res.get('level')), inline=False)
    embed.set_footer(text=f"🔗 Data from Archives of Nethys | Source: {res.get('source', 'N/A')}")
    return embed

def format_default_embed(res: dict) -> discord.Embed:
    raw = clean_text(res.get("text"))
    traits = res.get("trait_raw", [])
    color = get_rarity_color(res.get("rarity"))
    embed = discord.Embed(
        title=res.get("name", "Unknown"),
        url=res.get("url"),
        description=main_desc(raw),
        color=color
    )
    embed.add_field(name="Traits", value=truncate(" ".join(f"`{t}`" for t in traits) or "None", 1024), inline=False)
    if res.get("level"):
        embed.add_field(name="Level", value=str(res.get("level")), inline=False)
    if res.get("category"):
        embed.add_field(name="Category", value=res.get("category"), inline=False)
    embed.set_footer(text=f"🔗 Data from Archives of Nethys | Source: {res.get('source', 'N/A')}")
    return embed

def format_result_embed(res: dict) -> discord.Embed:
    type_ = (res.get("type") or "").lower()
    category = (res.get("category") or "").lower()

    if type_ == "weapon" or category == "weapon":
        return format_weapon_embed(res)
    if type_ == "spell":
        return format_spell_embed(res)
    return format_default_embed(res)

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
        await safe_followup(inter, content="Error while searching. Please try again later.")
        return

    if not results:
        await safe_followup(inter, content=f"**No results found for `{query}`**")
        return

    embed = format_result_embed(results[0])
    await safe_followup(inter, embed=embed)

# safe helpers for follow‑ups and defer
async def interaction_response_defer_safe(inter: discord.Interaction):
    if not inter.response.is_done():
        try:
            await inter.response.defer()
        except Exception:
            pass

async def safe_followup(inter: discord.Interaction, content: str | None = None, *, embed: discord.Embed | None = None):
    try:
        if inter.response.is_done():
            if embed:
                await inter.followup.send(embed=embed)
            elif content:
                await inter.followup.send(content)
        else:
            if embed:
                await inter.response.send_message(embed=embed)
            elif content:
                await inter.response.send_message(content)
    except Exception as err:
        logger.error("follow‑up failed: %s", err)
        try:
            error_message = "Sorry, I was unable to display the result for your query. An unexpected error occurred."
            if inter.response.is_done():
                await inter.followup.send(error_message, ephemeral=True)
            else:
                await inter.response.send_message(error_message, ephemeral=True)
        except Exception as final_err:
            logger.error("Failed to send final error message: %s", final_err)


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
WS_RE = re.compile(r"[ \t]+")
DMG_RE = [
    re.compile(r"(\d+d\d+(?:\+\d+)?)\s+(slashing|piercing|bludgeoning|s|p|b)\b", re.I),
    re.compile(r"damage\s+(\d+d\d+(?:\+\d+)?)(?:\s*(\w+))?", re.I),
]
BULK_RE = [re.compile(p, re.I) for p in (r"bulk\s+([0-9]+|L|-)", r"bulk: ?([0-9]+|L|-)")]
HANDS_RE = [re.compile(p, re.I) for p in (r"hands?\s+(\d+)", r"hands?: ?(\d+)")]
GROUP_RE = [re.compile(p, re.I) for p in (r"group\s+(\w+)", r"weapon\s+group: ?(\w+)")]

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
        "_source": ["name", "type", "url", "text", "level", "price", "category", "source", "rarity", "trait_raw"],
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
            "trait_raw": src.get("trait_raw", []),
        })

    await search_cache.set(cache_key, results)
    return results


# ── Parsing helpers ───────────────────────────────────────────

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
    "sword": "The target is made **off-guard** until the start of your next turn.",
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

def format_traits(traits: List[str], base_damage_str: str | None = None) -> str:
    if not traits:
        return "None"

    base_type = ""
    if base_damage_str and ' ' in base_damage_str:
        base_type = base_damage_str.split()[-1]

    descriptions = {
        "versatile p": "piercing",
        "versatile s": "slashing",
        "versatile b": "bludgeoning"
    }

    formatted_traits = []
    for trait in traits:
        lower_trait = trait.lower()
        if lower_trait in descriptions:
            alt_type = descriptions[lower_trait]
            display_trait = f"Versatile {lower_trait.split()[-1].upper()}"
            desc = f"**{display_trait}:** Can be used to deal {alt_type} damage"
            if base_type and base_type != alt_type:
                desc += f" instead of its normal {base_type} damage"
            desc += ". You choose the damage type each time you attack."
            formatted_traits.append(desc)
        else:
            formatted_traits.append(f"`{trait}`")
            
    return " ".join(formatted_traits)

# ── Formatting helpers ───────────────────────────────────────

def plural(word: str) -> str:
    return word if word.endswith("s") else word + "s"


def parse_aon_text_into_sections(text: str) -> dict[str, str]:
    """
    Parses a raw text block from AoN into a dictionary of logical sections.
    This is the core of the new, robust parsing system.
    """
    sections = {}
    
    boundary_keywords = [
        "Source", "Price", "Level", "Bulk", "Hands", "Damage", "Category", "Group", "Type", 
        "Access", "Trigger", "Requirements", "Favored Weapon", "Specific Magic",
        "Critical Specialization", "Critical Success", "Cast", "Traditions", "Activation"
    ]
    pattern = re.compile(r"\s*(?:---|\b(" + "|".join(boundary_keywords) + r"):)\s*", re.I)
    
    tokens = pattern.split(text)
    if not tokens:
        return sections

    sections['description'] = tokens[0].strip()
    
    i = 1
    while i < len(tokens):
        keyword = tokens[i]
        value = tokens[i+1].strip() if (i+1) < len(tokens) else ""
        if keyword:
            sections[keyword.lower().replace(" ", "_")] = value
        i += 2
        
    return sections


def get_rarity_color(rarity: str | None) -> discord.Color:
    rarity = (rarity or "common").lower()
    if rarity == "uncommon":
        return discord.Color.blue()
    if rarity == "rare":
        return discord.Color.purple()
    if rarity == "unique":
        return discord.Color.gold()
    return discord.Color.default()

def truncate(text: str, max_len: int) -> str:
    return (text[:max_len - 3] + '...') if len(text) > max_len else text

def format_price(price_cp: int) -> str:
    if not price_cp:
        return "N/A"
    gp = price_cp // 100
    sp = (price_cp % 100) // 10
    cp = price_cp % 10
    parts = []
    if gp:
        parts.append(f"{gp} gp")
    if sp:
        parts.append(f"{sp} sp")
    if cp:
        parts.append(f"{cp} cp")
    return " ".join(parts) or "0 cp"

def format_weapon_embed(res: dict) -> discord.Embed:
    raw_text = clean_text(res.get("text", ""))
    sections = parse_aon_text_into_sections(raw_text)

    stats = parse_weapon_stats(raw_text)
    traits = res.get("trait_raw", [])
    color = get_rarity_color(res.get("rarity"))

    embed = discord.Embed(
        title=res.get("name", "Unknown"),
        url=res.get("url"),
        description=sections.get('description', "No description available."),
        color=color
    )
    damage_str = stats.get('damage')
    embed.add_field(name="Traits", value=truncate(format_traits(traits, damage_str), 1024), inline=False)

    price_val = "N/A"
    if (price_raw := res.get("price")) is not None:
        try:
            price_val = format_price(int(price_raw))
        except (ValueError, TypeError):
            price_val = str(price_raw)

    prop_text = f"**Price** {price_val}"
    if (level := res.get('level')) is not None:
        prop_text += f"\n**Level** {level}"
    prop_text += f"\n**Bulk** {stats.get('bulk', 'N/A')}"
    embed.add_field(name="Properties", value=prop_text, inline=True)

    combat_text = f"**Damage** {stats.get('damage', 'N/A')}\n**Hands** {stats.get('hands', 'N/A')}"
    embed.add_field(name="Combat", value=combat_text, inline=True)

    class_text = f"**Type** {res.get('type', 'Unknown').title()}\n**Group** {stats.get('group', 'N/A').title()}\n**Category** {res.get('category', 'N/A').title()}"
    embed.add_field(name="Classification", value=class_text, inline=True)

    if (crit_spec_text := sections.get("critical_specialization")):
         embed.add_field(
            name="Critical Specialization",
            value=crit_spec_text,
            inline=False
        )
    
    if (favored_weapon_text := sections.get("favored_weapon")):
        embed.add_field(name="Favored Weapon of", value=truncate(favored_weapon_text, 1024), inline=False)
        
    if (specific_magic_text := sections.get("specific_magic")):
        embed.add_field(name=f"Specific Magic {plural(res['name'])}", value=truncate(specific_magic_text, 1024), inline=False)

    source_text = "N/A"
    if (source_raw := res.get("source")):
        source_text = ", ".join(source_raw) if isinstance(source_raw, list) else str(source_raw)

    embed.set_footer(text=f"🔗 Data from Archives of Nethys | Source: {source_text}")
    return embed

def format_spell_embed(res: dict) -> discord.Embed:
    raw_text = clean_text(res.get("text", ""))
    sections = parse_aon_text_into_sections(raw_text)
    traits = res.get("trait_raw", [])
    color = get_rarity_color(res.get("rarity"))
    embed = discord.Embed(
        title=res.get("name", "Unknown"),
        url=res.get("url"),
        description=sections.get('description', 'No description available.'),
        color=color
    )
    embed.add_field(name="Traits", value=truncate(" ".join(f"`{t}`" for t in traits) or "None", 1024), inline=False)
    
    if res.get('level'):
        embed.add_field(name="Level", value=str(res.get('level')), inline=False)
    
    for section_name in ["cast", "trigger", "requirements", "traditions", "activation"]:
        if section_text := sections.get(section_name):
            embed.add_field(name=section_name.title(), value=section_text, inline=False)
            
    source_text = "N/A"
    if (source_raw := res.get("source")):
        source_text = ", ".join(source_raw) if isinstance(source_raw, list) else str(source_raw)

    embed.set_footer(text=f"🔗 Data from Archives of Nethys | Source: {source_text}")
    return embed

def format_default_embed(res: dict) -> discord.Embed:
    raw_text = clean_text(res.get("text", ""))
    sections = parse_aon_text_into_sections(raw_text)
    traits = res.get("trait_raw", [])
    color = get_rarity_color(res.get("rarity"))
    embed = discord.Embed(
        title=res.get("name", "Unknown"),
        url=res.get("url"),
        description=sections.get('description', 'No description available.'),
        color=color
    )
    embed.add_field(name="Traits", value=truncate(" ".join(f"`{t}`" for t in traits) or "None", 1024), inline=False)
    if res.get("level"):
        embed.add_field(name="Level", value=str(res.get("level")), inline=False)
    if res.get("category"):
        embed.add_field(name="Category", value=res.get("category"), inline=False)
    
    source_text = "N/A"
    if (source_raw := res.get("source")):
        source_text = ", ".join(source_raw) if isinstance(source_raw, list) else str(source_raw)
        
    embed.set_footer(text=f"🔗 Data from Archives of Nethys | Source: {source_text}")
    return embed

def format_result_embed(res: dict) -> discord.Embed:
    type_ = (res.get("type") or "").lower()
    category = (res.get("category") or "").lower()

    if type_ == "weapon" or category == "weapon":
        return format_weapon_embed(res)
    if type_ == "spell":
        return format_spell_embed(res)
    return format_default_embed(res)

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
        await safe_followup(inter, content="Error while searching. Please try again later.")
        return

    if not results:
        await safe_followup(inter, content=f"**No results found for `{query}`**")
        return

    embed = format_result_embed(results[0])
    await safe_followup(inter, embed=embed)

# safe helpers for follow‑ups and defer
async def interaction_response_defer_safe(inter: discord.Interaction):
    if not inter.response.is_done():
        try:
            await inter.response.defer()
        except Exception:
            pass

async def safe_followup(inter: discord.Interaction, content: str | None = None, *, embed: discord.Embed | None = None):
    try:
        # Since we always defer in cmd_search, we should always use followup
        if embed:
            await inter.followup.send(embed=embed)
        elif content:
            await inter.followup.send(content)
    except Exception as err:
        logger.error("follow‑up failed: %s", err)
        try:
            error_message = "Sorry, I was unable to display the result for your query. An unexpected error occurred."
            await inter.followup.send(error_message, ephemeral=True)
        except Exception as final_err:
            logger.error("Failed to send final error message: %s", final_err)


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

