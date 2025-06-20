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
import json

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
import openai

# ── Logging ─────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("pf2e-bot")

# ── Configuration ─────────────────────────────────────────────
TOKEN = os.getenv("DiscordOracle") or os.getenv("DISCORD_TOKEN")
if not TOKEN:
    logger.error("Discord token missing (DiscordOracle / DISCORD_TOKEN)")
    sys.exit(1)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    logger.warning("OPENAI_API_KEY not found. AI formatting will be disabled.")
    
client = openai.AsyncOpenAI(api_key=OPENAI_API_KEY)

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

def main_desc(text: str) -> str:
    # Descriptions on AoN are typically separated from the stat block by a horizontal rule,
    # which often becomes '---' in the text blob.
    parts = text.split('---', 1)
    
    desc = "No description available."

    if len(parts) > 1 and parts[1].strip():
        # We found a description after the separator
        desc_text = parts[1].strip()
        
        # Clean up any remaining boilerplate from this section
        sents = [s.strip() for s in desc_text.split('.') if len(s.strip()) > 10]
        bad_keywords = (
             "critical specialization",
             "favored weapon"
        )
        keep = [s for s in sents if not any(k in s.lower() for k in bad_keywords)]
        
        # Join the kept sentences, ensuring it ends with a period.
        if keep:
            desc = ". ".join(keep)
            if not desc.endswith('.'):
                desc += '.'
        else:
            # If all sentences were filtered, use the original text but clean it.
            desc = desc_text.split("Critical Specialization Effects")[0].strip()

    else:
        # Fallback for items that might not have the separator
        sents = [s.strip() for s in text.split(".") if len(s.strip()) > 15]
        bad_keywords = (
            "source", "favored weapon", "specific magic", "price", "bulk", "hands",
            "damage", "category", "group", "type", "level", "critical success",
            "critical specialization"
        )
        keep = [s for s in sents if not any(k in s.lower() for k in bad_keywords)]
        if keep:
            desc = (". ".join(keep[:2]) + ".")
    
    return (desc[:4093] + '...') if len(desc) > 4096 else desc

# ── Formatting helpers ───────────────────────────────────────

def plural(word: str) -> str:
    return word if word.endswith("s") else word + "s"


def first_after(label: str, text: str) -> Optional[str]:
    """
    Finds the text immediately following a given label in a block of text.
    It stops parsing when it hits another known section label or a separator.
    """
    # Use a case-insensitive search for the label
    match = re.search(fr"\b{re.escape(label)}\b", text, re.IGNORECASE)
    if not match:
        return None

    # The content starts after the matched label
    start_index = match.end()
    
    # We strip away any colons or whitespace that might follow the label
    content_part = text[start_index:].lstrip(": ")

    # Define keywords that mark the beginning of a new, unrelated section.
    # The search for these should be case-insensitive.
    stop_keywords = [
        "price", "damage", "bulk", "hands", "type", "category", "group", 
        "critical specialization", "favored weapon", "specific magic", 
        "source", "ammunition", "reload", "range", "---", "level"
    ]

    # Find the earliest occurrence of any stop keyword in the rest of the text.
    end_index = len(content_part)
    lower_content = content_part.lower()

    for keyword in stop_keywords:
        # Don't let the label stop itself if it appears in the content
        if keyword in label.lower():
            continue
        
        try:
            # Find the position of the keyword
            found_pos = lower_content.index(keyword)
            # We want the *earliest* stop position
            end_index = min(end_index, found_pos)
        except ValueError:
            # The keyword wasn't found, so we continue
            continue
            
    # Extract the substring and clean up any trailing whitespace or punctuation
    result = content_part[:end_index].strip().rstrip(".,;")
    
    # If the result is just a single character (like a leftover letter), it's probably junk.
    if len(result) <= 1:
        return None

    return result


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

async def format_weapon_embed_with_gpt(res: dict) -> discord.Embed:
    """
    Uses GPT-4o Mini to format the weapon embed from raw AoN JSON data.
    """
    if not OPENAI_API_KEY:
        return format_default_embed(res)

    prompt = f"""
You are an expert Pathfinder 2e Discord Bot Assistant. Your role is to receive raw JSON data from the Archives of Nethys (AoN) API and transform it into a structured JSON object that can be used to create a Discord embed.

RULES:
1.  Parse the input JSON and create a new JSON object with the following keys: `title`, `url`, `description`, and `fields`.
2.  `title`: The item's name.
3.  `url`: The item's AoN URL.
4.  `description`: The item's flavor text. Extract this from the `text` field, usually after a '---' separator. Filter out boilerplate sentences about "critical specialization" or "favored weapon".
5.  `fields`: An array of field objects. Each object must have `name`, `value`, and `inline` (boolean) keys.
6.  Create the following fields, ensuring all values are strings:
    *   **Traits**: `inline: false`. For the "Versatile" trait, provide the detailed explanation: "Can be used to deal [alternate type] damage instead of its normal [base type] damage. You choose the damage type each time you attack." Other traits should be `code-ticked`.
    *   **Properties**: `inline: true`. Value should contain Price, Level, and Bulk, each on a new line.
    *   **Combat**: `inline: true`. Value should contain Damage and Hands, each on a new line.
    *   **Classification**: `inline: true`. Value should contain Type, Group, and Category, each on a new line.
    *   **Critical Specialization Effects**: `inline: false`. The value must be formatted as: "**[Group Name]**: [Effect Text] (optional effect).\\nCertain feats, class features, weapon runes, and other effects can grant you additional benefits (might be mandatory)." Use "off-guard".
    *   **Favored Weapon of**: If present, create this field. `inline: false`. Extract the list of deities.
    *   **Specific Magic...**: If present, create this field. `inline: false`. Extract the list of specific weapons.

Return ONLY the JSON object. Do not wrap it in markdown backticks or explain yourself.

INPUT DATA:
{json.dumps(res, indent=2)}

JSON OUTPUT:
"""

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        content = response.choices[0].message.content
        embed_data = json.loads(content)

        color = get_rarity_color(res.get("rarity"))
        embed = discord.Embed(
            title=embed_data.get("title"),
            url=embed_data.get("url"),
            description=embed_data.get("description"),
            color=color
        )

        for field in embed_data.get("fields", []):
            embed.add_field(
                name=field.get("name"),
                value=field.get("value"),
                inline=field.get("inline", False)
            )
        
        embed.set_footer(text=f"🔗 Data from Archives of Nethys | Source: {res.get('source', 'N/A')}")
        return embed

    except Exception as e:
        logger.error(f"Error formatting with GPT: {e}")
        # Fallback to the old method if GPT fails
        return format_default_embed(res)

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

async def format_result_embed(res: dict) -> discord.Embed:
    type_ = (res.get("type") or "").lower()
    category = (res.get("category") or "").lower()

    if type_ == "weapon" or category == "weapon":
        return await format_weapon_embed_with_gpt(res)
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

    embed = await format_result_embed(results[0])
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



