# main.py – Simple PF2e Discord Bot with Slash Commands (final, syntax‑clean)
# -------------------------------------------------------------------
# • Shared aiohttp session
# • Robust 2 000‑char splitter
# • Clickable URL in output
# • Adaptive formatting for different result types
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
# IMPORTANT: Use environment variables or a .env file for your token in production.
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
            if not val:
                return None
            data, ts = val
            if time.time() - ts < self.ttl:
                return data
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
    """Removes HTML tags and cleans up whitespace."""
    if not text:
        return ""
    text = TAG_RE.sub("", text)
    text = unescape(text)
    return WS_RE.sub(" ", text).strip()

async def search_aon_api(query: str, *, result_limit: int = 5, category_filter: str | None = None):
    """Searches the Archives of Nethys Elasticsearch API."""
    key = f"{query}:{result_limit}:{category_filter}"
    if (cached := await search_cache.get(key)) is not None:
        return cached

    if _http_session is None:
        raise RuntimeError("HTTP session not ready")

    bool_q = {
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
        bool_q.setdefault("filter", []).append({"term": {"type.keyword": category_filter}})

    body = {
        "query": {"bool": bool_q},
        "size": result_limit,
        "_source": ["name", "type", "url", "text", "level", "price", "category", "source", "rarity"],
        "sort": [{"_score": "desc"}, {"name.keyword": "asc"}],
    }

    try:
        async with _http_session.post(
            AON_API_BASE,
            json=body,
            headers={"User-Agent": "PF2E Discord Bot"},
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
    except aiohttp.ClientError as e:
        logger.error("AON API request failed: %s", e)
        return []

    results = []
    for hit in data.get("hits", {}).get("hits", []):
        src = hit.get("_source", {})
        url = src.get("url", "")
        if url and not url.startswith("http"):
            url = AON_WEB_BASE + url.lstrip("/")
        results.append({
            "name": src.get("name", "Unknown"), "type": src.get("type", "Unknown"),
            "url": url, "text": src.get("text", ""), "level": src.get("level"),
            "price": src.get("price"), "category": src.get("category"),
            "source": src.get("source"), "rarity": src.get("rarity"),
        })

    await search_cache.set(key, results)
    return results

# ── Parsing helpers ───────────────────────────────────────────

def parse_traits(text: str) -> list[str]:
    out = []
    seen = set()
    for m in TRAIT_RE.finditer(text):
        tok = m.group(0)
        if tok.lower().startswith("versatile"):
            tok = f"Versatile {tok.split()[-1].upper()}"
        else:
            tok = tok.title()
        if tok not in seen:
            seen.add(tok)
            out.append(tok)
    return out

def parse_weapon_stats(text: str) -> dict[str, str]:
    stats: dict[str, str] = {}
    for r in DMG_RE:
        if m := r.search(text):
            die, typ = m.groups(default="")
            typ = typ.lower()
            typ_map = {"s": "slashing", "p": "piercing", "b": "bludgeoning"}
            stats["damage"] = f"{die} {typ_map.get(typ, typ or 'slashing')}"
            break
    for r in BULK_RE:
        if m := r.search(text):
            stats["bulk"] = m.group(1)
            break
    for r in HANDS_RE:
        if m := r.search(text):
            stats["hands"] = m.group(1)
            break
    if "hands" not in stats:
        stats["hands"] = "2" if "two-hand" in text.lower() else "1"
    for r in GROUP_RE:
        if m := r.search(text):
            stats["group"] = m.group(1).lower()
            break
    return stats

CRIT = {
    "sword": "Target becomes **flat-footed** until the start of your next turn.",
    "axe": "Choose an adjacent creature to take damage equal to the weapon's number of damage dice.",
    "bow": "Target is **immobilized** and must spend an Interact action to attempt a DC 10 Athletics check to escape.",
    "club": "Move the target 5 feet (or 10 feet on a critical hit with a greater crushing rune).",
    "flail": "The target is knocked **prone**.",
    "hammer": "The target is knocked **prone**.",
    "knife": "Target takes 1d6 persistent bleed damage.",
    "polearm": "You can move the target 5 feet in a direction of your choice.",
    "spear": "Target takes a –2 circumstance penalty to its attack rolls against you until the start of your next turn.",
}

def crit_effect(group: str | None) -> str:
    return CRIT.get((group or "").lower(), "No specific critical specialization effect.")

# ── Formatting ────────────────────────────────────────────────

def create_header(res: dict) -> list[str]:
    """Creates a standardized header for any result type."""
    name_line = res["name"]
    rarity = res.get("rarity")
    if rarity and rarity.lower() != "common":
        name_line += f" ({rarity.title()})"
    
    lines = [f"**{name_line}**"]
    if res.get("url"):
        lines.append(f"<{res['url']}>")
    
    traits = parse_traits(clean_text(res.get("text", "")))
    if traits:
        lines.append("".join(f"［{t}］" for t in traits))
    
    return lines

def format_weapon(res: dict) -> str:
    """Formats a weapon result for Discord."""
    lines = create_header(res)
    raw_text = clean_text(res.get("text", ""))
    stats = parse_weapon_stats(raw_text)

    # Main description - trying to find a clean sentence.
    desc_match = re.search(r'</h1.*?<br />\s*(.*?)\s*<br />', res.get("text", ""), re.DOTALL)
    description = clean_text(desc_match.group(1)) if desc_match else "A martial or simple weapon."
    lines.append("\n" + description)

    lines.append("\n**Weapon Stats**")
    if res.get("price"): lines.append(f"**Price**: {res['price']}")
    if stats.get("damage"): lines.append(f"**Damage**: {stats['damage']}")
    
    hand_bulk = []
    if stats.get("hands"): hand_bulk.append(f"**Hands**: {stats['hands']}")
    if stats.get("bulk"): hand_bulk.append(f"**Bulk**: {stats['bulk']}")
    if hand_bulk: lines.append(" | ".join(hand_bulk))

    if group := stats.get("group"):
        lines.append(f"**Group**: {group.title()}")
        lines.append(f"**Crit Spec**: {crit_effect(group)}")
    
    return "\n".join(lines)

def format_generic(res: dict) -> str:
    """A generic fallback formatter for any other item type."""
    lines = create_header(res)
    raw_text = clean_text(res.get("text", ""))

    # Extract level, source, and a brief description
    if level := res.get("level"): lines.insert(1, f"**{res['type'].title()} {level}**")
    if source := res.get("source"): lines.append(f"**Source**: {source}")

    # A simple heuristic to get the main description text
    sents = [s.strip() for s in raw_text.split(".") if len(s.strip()) > 20]
    keep = [s for s in sents if not any(k in s.lower() for k in ("source", "price", "level", "rarity"))]
    description = ". ".join(keep[:3]) + ("." if keep else "")
    
    lines.append("\n" + (description or "No description available."))
    return "\n".join(lines)

def format_result(res: dict) -> str:
    """Dispatcher to select the correct formatter based on result type."""
    res_type = res.get("type", "generic").lower()

    if res_type == "equipment" and res.get("category", "").lower() == "weapon":
        return format_weapon(res)
    
    # Can add more specific formatters here, e.g., for "spell", "feat"
    # elif res_type == "spell":
    #     return format_spell(res)
    
    return format_generic(res)

async def send_long_message(interaction: discord.Interaction, text: str):
    """Sends a message, splitting it into multiple chunks if it exceeds 2000 chars."""
    if len(text) <= 2000:
        await interaction.followup.send(text)
        return

    chunks = []
    current_chunk = ""
    for line in text.split('\n'):
        if len(current_chunk) + len(line) + 1 > 2000:
            chunks.append(current_chunk)
            current_chunk = ""
        current_chunk += line + "\n"
    
    if current_chunk:
        chunks.append(current_chunk)

    # Send the first chunk as the initial followup
    if chunks:
        await interaction.followup.send(chunks[0])
    # Send subsequent chunks as new messages
    for chunk in chunks[1:]:
        await interaction.channel.send(chunk)


# ── Bot Setup ───────────────────────────────────────────────

class Pf2eBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)

    async def on_ready(self):
        await self.wait_until_ready()
        logger.info(f"Logged in as {self.user} (ID: {self.user.id})")
        logger.info("Syncing command tree...")
        await self.tree.sync()
        logger.info("Command tree synced.")

    async def setup_hook(self) -> None:
        """Initialize the aiohttp session."""
        global _http_session
        _http_session = aiohttp.ClientSession()
        logger.info("AIOHTTP client session started.")

    async def close(self) -> None:
        """Close the aiohttp session on shutdown."""
        if _http_session:
            await _http_session.close()
            logger.info("AIOHTTP client session closed.")
        await super().close()

bot = Pf2eBot()

@bot.tree.command(name="search", description="Search the Archives of Nethys for a PF2e rule, item, spell, etc.")
@app_commands.describe(
    query="What you want to search for (e.g., 'Bastard Sword', 'Magic Missile', 'Sudden Charge').",
    category="The category to search in. Defaults to 'All'."
)
@app_commands.choices(category=[
    app_commands.Choice(name=cat, value=cat) for cat in SEARCH_CATEGORIES
])
async def search(interaction: discord.Interaction, query: str, category: Optional[str] = "All"):
    """Handles the slash command logic for searching AoN."""
    await interaction.response.defer()
    
    try:
        results = await search_aon_api(query, result_limit=5, category_filter=category)
        if not results:
            await interaction.followup.send(f"No results found for **{query}** in category **{category}**.")
            return

        # For this simple bot, we'll just format and show the top result.
        # A more complex bot might show a select menu to choose from the `results` list.
        top_result = results[0]
        response_text = format_result(top_result)
        
        await send_long_message(interaction, response_text)

    except Exception as e:
        logger.error(f"Error during search command: {e}", exc_info=True)
        await interaction.followup.send("An unexpected error occurred. Please try again later.")


# ── Run Bot ─────────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        bot.run(TOKEN)
    except discord.LoginFailure:
        logger.error("Failed to log in. Please check your Discord token.")
    except Exception as e:
        logger.error(f"An error occurred while running the bot: {e}")
