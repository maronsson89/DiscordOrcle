# main.py – (v3) With Detailed Formatting for Spells & Feats
# -------------------------------------------------------------------
# • Restored detailed formatting for spells and feats.
# • Shared aiohttp session
# • Robust 2 000‑char splitter
# • Clickable URL in output
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

# ── Logging ────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("pf2e-bot")

# ── Configuration ─────────────────────────────────────────────
TOKEN = os.getenv("DiscordOracle") or os.getenv("DISCORD_TOKEN")
if not TOKEN:
    logger.error("Discord token missing (DiscordOracle / DISCORD_TOKEN). Exiting…")
    sys.exit(1)

AON_API_BASE = "https://elasticsearch.aonprd.com/aon/_search"
AON_WEB_BASE = "https://2e.aonprd.com/"

SEARCH_CATEGORIES = [
    "All", "Action", "Ancestry", "Background", "Class", "Condition",
    "Equipment", "Feat", "Hazard", "Monster", "Rule", "Spell", "Trait",
]

# ── Globals ───────────────────────────────────────────────────
_http_session: aiohttp.ClientSession | None = None

# ── Simple TTL cache ──────────────────────────────────────────
class SearchCache:
    def __init__(self, ttl: int = 300):
        self.ttl = ttl
        self.cache: dict[str, tuple[object, float]] = {}
        self.lock = asyncio.Lock()

    async def get(self, key: str):
        async with self.lock:
            val = self.cache.get(key)
            if not val: return None
            data, ts = val
            if time.time() - ts < self.ttl: return data
            del self.cache[key]
            return None

    async def set(self, key: str, value):
        async with self.lock:
            self.cache[key] = (value, time.time())

search_cache = SearchCache()

# ── Regexes ───────────────────────────────────────────────────
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
    r'\b(uncommon|rare|unique|attack|manipulate|auditory|visual|concentrate|move|backswing|disarm|reach|trip|finesse|agile|deadly|fatal|parry|sweep|forceful|shove|twin|monk|unarmed|free-hand|grapple|nonlethal|propulsive|volley|ranged|thrown|versatile\s+[a-z])\b',
    re.I,
)

# ── Utility helpers ───────────────────────────────────────────

def clean_text(text: str | None) -> str:
    if not text: return ""
    text = TAG_RE.sub("", text)
    text = unescape(text)
    return WS_RE.sub(" ", text).strip()

async def search_aon_api(query: str, *, result_limit: int = 5, category_filter: str | None = None):
    key = f"{query}:{result_limit}:{category_filter}"
    if (cached := await search_cache.get(key)) is not None:
        return cached

    if _http_session is None: raise RuntimeError("HTTP session not ready")

    bool_q = {
        "should": [
            {"multi_match": {"query": query, "fields": ["name^3", "text^2", "trait_raw^2"], "type": "best_fields", "fuzziness": "AUTO"}},
            {"wildcard": {"name.keyword": f"*{query.lower()}*"}},
        ], "minimum_should_match": 1,
    }
    if category_filter and category_filter != "All":
        bool_q.setdefault("filter", []).append({"term": {"type.keyword": category_filter}})

    body = {
        "query": {"bool": bool_q}, "size": result_limit,
        "_source": ["name", "type", "url", "text", "level", "price", "category", "source", "rarity"],
        "sort": [{"_score": "desc"}, {"name.keyword": "asc"}],
    }

    try:
        async with _http_session.post(AON_API_BASE, json=body, headers={"User-Agent": "PF2E Discord Bot"}) as resp:
            resp.raise_for_status()
            data = await resp.json()
    except aiohttp.ClientError as e:
        logger.error("AON API request failed: %s", e)
        return []

    results = []
    for hit in data.get("hits", {}).get("hits", []):
        src = hit.get("_source", {})
        url = src.get("url", "")
        if url and not url.startswith("http"): url = AON_WEB_BASE + url.lstrip("/")
        results.append({
            "name": src.get("name", "Unknown"), "type": src.get("type", "Unknown"),
            "url": url, "text": src.get("text", ""), "level": src.get("level"),
            "price": src.get("price"), "category": src.get("category"),
            "source": src.get("source"), "rarity": src.get("rarity"),
        })

    await search_cache.set(key, results)
    return results

# ── Parsing helpers ───────────────────────────────────────────

def parse_field(field_name: str, text: str) -> Optional[str]:
    """Generic helper to find a field like 'Source' or 'Cast' in text."""
    match = re.search(fr"{field_name}</strong>\s*([^<]+)", text, re.I)
    return clean_text(match.group(1)) if match else None

def get_main_description(text: str) -> str:
    """Extracts the main descriptive text, typically after the initial block of stats."""
    # Find the end of the last stat block (like '---') or the first major paragraph break
    match = re.search(r'(<hr\s?/?>|</h1.*?<br />)', text, re.DOTALL)
    start_pos = match.end() if match else 0
    description = clean_text(text[start_pos:])
    
    # Clean up any leading "Source" or other field remnants
    description = re.sub(r"^(Source|Prerequisites|Requirements|Trigger|Frequency)[\s\w:]+", "", description).strip()
    return description or "No description available."


# ── Formatting ────────────────────────────────────────────────

def create_header(res: dict) -> list[str]:
    name_line = res["name"]
    rarity = res.get("rarity")
    if rarity and rarity.lower() != "common":
        name_line += f" ({rarity.title()})"
    
    level_text = f"**{res['type'].title()} {res['level']}**" if res.get("level") else f"**{res['type'].title()}**"
    lines = [f"**{name_line}**", level_text]
    if res.get("url"): lines.append(f"<{res['url']}>")
    
    traits = parse_traits(clean_text(res.get("text", "")))
    if traits: lines.append("".join(f"［{t}］" for t in traits))
    
    if source := res.get("source"): lines.append(f"**Source**: {source}")
    return lines

def format_weapon(res: dict) -> str:
    lines = create_header(res)
    raw_text_html = res.get("text", "")
    stats = parse_weapon_stats(clean_text(raw_text_html))
    
    lines.append("\n" + get_main_description(raw_text_html))
    lines.append("\n**Weapon Stats**")
    if res.get("price"): lines.append(f"**Price**: {res['price']}")
    if stats.get("damage"): lines.append(f"**Damage**: {stats['damage']}")
    
    hand_bulk = [f"**Hands**: {stats['hands']}" if 'hands' in stats else None, f"**Bulk**: {stats['bulk']}" if 'bulk' in stats else None]
    lines.append(" | ".join(filter(None, hand_bulk)))
    
    if group := stats.get("group"):
        crit_effect_map = {"sword": "Target becomes flat-footed.", "axe": "Deal damage to an adjacent creature.", "bow": "Target is immobilized.", "club": "Move the target 5 feet.", "flail": "Target is knocked prone.", "hammer": "Target is knocked prone.", "knife": "Target takes 1d6 persistent bleed damage.", "polearm": "You can move the target 5 feet.", "spear": "Target takes a –2 circumstance penalty to attack rolls against you."}
        lines.append(f"**Group**: {group.title()} | **Crit Spec**: {crit_effect_map.get(group, 'None')}")
    
    return "\n".join(lines)

def format_spell(res: dict) -> str:
    lines = create_header(res)
    raw_text_html = res.get("text", "")
    
    if traditions := parse_field("Traditions", raw_text_html): lines.append(f"**Traditions**: {traditions}")
    if cast := parse_field("Cast", raw_text_html): lines.append(f"**Cast**: {cast}")
    if range_field := parse_field("Range", raw_text_html): lines.append(f"**Range**: {range_field}")
    if targets := parse_field("Targets", raw_text_html): lines.append(f"**Targets**: {targets}")
    if duration := parse_field("Duration", raw_text_html): lines.append(f"**Duration**: {duration}")
    
    lines.append("\n" + get_main_description(raw_text_html))
    return "\n".join(lines)

def format_feat(res: dict) -> str:
    lines = create_header(res)
    raw_text_html = res.get("text", "")

    if prereqs := parse_field("Prerequisites", raw_text_html): lines.append(f"**Prerequisites**: {prereqs}")
    if trigger := parse_field("Trigger", raw_text_html): lines.append(f"**Trigger**: {trigger}")

    lines.append("\n" + get_main_description(raw_text_html))
    return "\n".join(lines)

def format_generic(res: dict) -> str:
    lines = create_header(res)
    lines.append("\n" + get_main_description(res.get("text", "")))
    return "\n".join(lines)

def format_result(res: dict) -> str:
    """Dispatcher to select the correct formatter based on result type."""
    res_type = res.get("type", "generic").lower()

    if res_type == "spell":
        return format_spell(res)
    elif res_type == "feat":
        return format_feat(res)
    elif res_type == "equipment" and res.get("category", "").lower() == "weapon":
        return format_weapon(res)
    else:
        return format_generic(res)

async def send_long_message(interaction: discord.Interaction, text: str):
    if len(text) <= 2000:
        await interaction.followup.send(text)
        return
    chunks = [text[i:i + 2000] for i in range(0, len(text), 2000)]
    await interaction.followup.send(chunks[0])
    for chunk in chunks[1:]: await interaction.channel.send(chunk)

# ── Bot Setup and Commands ──────────────────────────────────
class Pf2eBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

    async def on_ready(self):
        logger.info(f"Logged in as {self.user}")
        await self.tree.sync()
        logger.info("Command tree synced.")

    async def setup_hook(self):
        global _http_session
        _http_session = aiohttp.ClientSession()

    async def close(self):
        if _http_session: await _http_session.close()
        await super().close()

bot = Pf2eBot()

@bot.tree.command(name="search", description="Search the Archives of Nethys for a PF2e rule, item, spell, etc.")
@app_commands.describe(query="What to search for.", category="The category to search in.")
@app_commands.choices(category=[app_commands.Choice(name=cat, value=cat) for cat in SEARCH_CATEGORIES])
async def search(interaction: discord.Interaction, query: str, category: Optional[str] = "All"):
    await interaction.response.defer()
    try:
        results = await search_aon_api(query, result_limit=5, category_filter=category)
        if not results:
            await interaction.followup.send(f"No results found for **{query}** in category **{category}**.")
            return
        
        response_text = format_result(results[0])
        await send_long_message(interaction, response_text)
    except Exception as e:
        logger.error(f"Error during search command: {e}", exc_info=True)
        await interaction.followup.send("An unexpected error occurred.")

# ── Run Bot ─────────────────────────────────────────────────────
if __name__ == "__main__":
    bot.run(TOKEN)
