# main.py - Simple PF2e Discord Bot with Slash Commands (No Images)

import discord
from discord.ext import commands
from discord import app_commands
import os
import aiohttp
import json
import logging
import re
from html import unescape
from typing import List, Optional
import time

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- CONFIGURATION ---
try:
    TOKEN = os.getenv('DiscordOracle')
    if TOKEN is None:
        logger.error("DiscordOracle environment variable not set.")
        exit()
    logger.info("Token loaded successfully")
except Exception as e:
    logger.error(f"Error reading environment variable: {e}")
    exit()

# Archives of Nethys Elasticsearch API
AON_API_BASE = "https://elasticsearch.aonprd.com/aon/_search"
AON_WEB_BASE = "https://2e.aonprd.com/"

# Search categories for filtering
SEARCH_CATEGORIES = [
    "Equipment", "Spell", "Feat", "Class", "Ancestry", "Background", 
    "Monster", "Hazard", "Rule", "Condition", "Trait", "Action"
]

# Simple cache for search results
class SearchCache:
    def __init__(self, ttl_seconds=300):
        self.cache = {}
        self.ttl = ttl_seconds
    
    def get(self, key):
        if key in self.cache:
            result, timestamp = self.cache[key]
            if time.time() - timestamp < self.ttl:
                return result
            del self.cache[key]
        return None
    
    def set(self, key, value):
        self.cache[key] = (value, time.time())

search_cache = SearchCache()

# --- UTILITY FUNCTIONS ---
def clean_text(text):
    """Clean HTML/XML tags and entities from text."""
    if not text:
        return ""
    
    text = re.sub(r'<[^>]+>', '', text)
    text = unescape(text)
    text = re.sub(r'\s+', ' ', text).strip()
    
    return text

async def search_aon_api(query: str, result_limit: int = 5, category_filter: str = None):
    """Search Archives of Nethys using their Elasticsearch API."""
    
    # Check cache first
    cache_key = f"{query}:{result_limit}:{category_filter}"
    cached_result = search_cache.get(cache_key)
    if cached_result:
        logger.info(f"Cache hit for: {query}")
        return cached_result
    
    logger.info(f"Searching API for: {query}")
    
    # Build search query
    bool_query = {
        "should": [
            {
                "multi_match": {
                    "query": query,
                    "fields": ["name^3", "text^2", "trait_raw^2"],
                    "type": "best_fields",
                    "fuzziness": "AUTO"
                }
            },
            {
                "wildcard": {
                    "name.keyword": f"*{query.lower()}*"
                }
            }
        ],
        "minimum_should_match": 1
    }
    
    # Add category filter if specified
    if category_filter and category_filter != "All":
        bool_query["filter"] = [{"term": {"type.keyword": category_filter}}]
    
    search_body = {
        "query": {"bool": bool_query},
        "size": result_limit,
        "_source": ["name", "type", "url", "text", "level", "price", "category", "source", "rarity"],
        "sort": [
            {"_score": {"order": "desc"}},
            {"name.keyword": {"order": "asc"}}
        ]
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                AON_API_BASE,
                json=search_body,
                headers={
                    'Content-Type': 'application/json',
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Accept': 'application/json',
                    'Referer': 'https://2e.aonprd.com/'
                },
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                response.raise_for_status()
                data = await response.json()
                
                results = []
                if 'hits' in data and 'hits' in data['hits']:
                    for hit in data['hits']['hits']:
                        source = hit['_source']
                        
                        # Build full URL
                        url = source.get('url', '')
                        if url and not url.startswith('http'):
                            url = AON_WEB_BASE + url.lstrip('/')
                        
                        result = {
                            'name': source.get('name', 'Unknown'),
                            'type': source.get('type', 'Unknown'),
                            'url': url,
                            'text': source.get('text', ''),
                            'level': source.get('level'),
                            'price': source.get('price'),
                            'category': source.get('category'),
                            'source': source.get('source'),
                            'rarity': source.get('rarity'),
                            'score': hit['_score']
                        }
                        results.append(result)
                
                # Cache results
                search_cache.set(cache_key, results)
                logger.info(f"Found {len(results)} results for: {query}")
                return results
                
    except Exception as e:
        logger.error(f"Search error for query '{query}': {e}")
        return []

def parse_traits_from_text(text):
    """Extract traits from item text."""
    traits = []
    # Look for trait patterns - more comprehensive list
    trait_patterns = [
        r'\bbackswing\b', r'\bdisarm\b', r'\breach\b', r'\btrip\b', r'\bfinesse\b',
        r'\bagile\b', r'\bdeadly\b', r'\bfatal\b', r'\bversatile\s+[a-z]\b', r'\bparry\b',
        r'\btwo-hand\b', r'\bthrown\b', r'\branged\b', r'\bvolley\b', r'\bforceful\b',
        r'\bshove\b', r'\bsweep\b', r'\btwin\b', r'\bmonk\b', r'\bunarmed\b',
        r'\bfree-hand\b', r'\bgrapple\b', r'\bnonlethal\b', r'\bpropulsive\b'
    ]
    
    for pattern in trait_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            trait_name = match.group(0)
            # Handle special case for versatile (include the damage type)
            if 'versatile' in trait_name.lower():
                versatile_match = re.search(r'versatile\s+([a-z])\b', text, re.IGNORECASE)
                if versatile_match:
                    damage_type = versatile_match.group(1).upper()
                    traits.append(f"Versatile {damage_type}")
                else:
                    traits.append("Versatile")
            else:
                traits.append(trait_name.title())
    
    return list(set(traits))  # Remove duplicates

def parse_weapon_stats(text, result):
    """Parse weapon-specific stats from text."""
    stats = {}
    
    # Extract damage - look for more specific patterns
    damage_patterns = [
        r'(\d+d\d+(?:\+\d+)?)\s+(slashing|piercing|bludgeoning|s|p|b)\b',
        r'damage\s+(\d+d\d+(?:\+\d+)?)\s*(\w+)?',
        r'(\d+d\d+)\s*(\w+)?\s+damage'
    ]
    
    for pattern in damage_patterns:
        damage_match = re.search(pattern, text, re.IGNORECASE)
        if damage_match:
            damage_die = damage_match.group(1)
            damage_type = damage_match.group(2) if len(damage_match.groups()) > 1 else None
            
            # Convert abbreviations to full names
            if damage_type:
                damage_type_map = {'s': 'slashing', 'p': 'piercing', 'b': 'bludgeoning'}
                damage_type = damage_type_map.get(damage_type.lower(), damage_type.lower())
            else:
                damage_type = "slashing"  # Default for swords
            
            stats['damage'] = f"{damage_die} {damage_type}"
            break
    
    # Extract bulk - look for more patterns
    bulk_patterns = [
        r'bulk\s+([0-9]+|L|-)\b',
        r'bulk:?\s*([0-9]+|L|-)',
        r'\bbulk\s+([0-9]+|L|-)'
    ]
    
    for pattern in bulk_patterns:
        bulk_match = re.search(pattern, text, re.IGNORECASE)
        if bulk_match:
            stats['bulk'] = bulk_match.group(1)
            break
    
    # Extract hands - look for more patterns
    hands_patterns = [
        r'hands?\s+(\d+)\b',
        r'hands?:?\s*(\d+)',
        r'(\d+)\s*hands?'
    ]
    
    for pattern in hands_patterns:
        hands_match = re.search(pattern, text, re.IGNORECASE)
        if hands_match:
            stats['hands'] = hands_match.group(1)
            break
    
    # Default hands based on weapon type if not found
    if 'hands' not in stats:
        if 'two-hand' in text.lower() or 'two hand' in text.lower():
            stats['hands'] = '2'
        else:
            stats['hands'] = '1'  # Most weapons are 1-handed
    
    # Try to extract group information - more patterns
    group_patterns = [
        r'group\s+(\w+)\b',
        r'weapon\s+group:?\s*(\w+)',
        r'group:?\s*(\w+)'
    ]
    
    for pattern in group_patterns:
        group_match = re.search(pattern, text, re.IGNORECASE)
        if group_match:
            stats['group'] = group_match.group(1).lower()
            break
    
    return stats

def create_embed_from_result(result, other_results=None):
    """Create a Discord embed from a search result matching the exact style."""
    
    embed = discord.Embed(
        color=discord.Color.dark_grey()
    )
    
    # Set the type as the author (top small text)
    if result.get('type'):
        embed.set_author(name=result['type'])
    
    # Main title with rarity in parentheses if not common
    title = result['name']
    if result.get('rarity') and result['rarity'].lower() != 'common':
        title = f"{result['name']} ({result['rarity']})"
    
    embed.title = title
    if result.get('url'):
        embed.url = result['url']
    
    # Get the raw text for parsing
    text = clean_text(result.get('text', ''))
    
    # Parse traits and weapon stats
    traits = parse_traits_from_text(text)
    weapon_stats = parse_weapon_stats(text, result)
    
    # Build the stats section exactly like the screenshot
    stats_lines = []
    
    # Add traits in brackets if found (first line)
    if traits:
        trait_string = "  ".join([f"[ {trait} ]" for trait in traits])
        stats_lines.append(trait_string)
    
    # Add level (for spells, feats, magic items - before price)
    if result.get('level') and result.get('level') != 0:
        stats_lines.append(f"**Level** {result['level']}")
    
    # Add price (second line)
    if result.get('price'):
        stats_lines.append(f"**Price** {result['price']}")
    
    # Add bulk and hands on same line (third line, weapon-specific)
    bulk_hands_parts = []
    if weapon_stats.get('bulk'):
        bulk_hands_parts.append(f"Bulk {weapon_stats['bulk']}")
    if weapon_stats.get('hands'):
        bulk_hands_parts.append(f"Hands {weapon_stats['hands']}")
    if bulk_hands_parts:
        stats_lines.append("**" + "; ".join(bulk_hands_parts) + "**")
    
    # Add damage (fourth line, weapon-specific)
    if weapon_stats.get('damage'):
        stats_lines.append(f"**Damage** {weapon_stats['damage']}")
    
    # Add category and group (fifth line) - comprehensive category info
    category_parts = []
    if result.get('category'):
        # Don't just show "weapon", show the proper category
        category = result['category']
        if category.lower() != 'weapon':
            category_parts.append(category)
        else:
            # For weapons, try to determine if it's martial, simple, etc.
            if 'martial' in text.lower():
                category_parts.append('martial melee weapon')
            elif 'simple' in text.lower():
                category_parts.append('simple melee weapon')
            else:
                category_parts.append('melee weapon')
    
    if weapon_stats.get('group'):
        category_parts.append(f"Group {weapon_stats['group']}")
    
    if category_parts:
        stats_lines.append("**Category** " + "; ".join(category_parts))
    
    # Add type as separate line if it's different from author and meaningful
    item_type = result.get('type')
    if item_type and item_type.lower() not in ['equipment', 'item', 'weapon']:
        stats_lines.append(f"**Type** {item_type}")
    
    # Add rarity as separate line if it's not common (additional to title)
    if result.get('rarity') and result['rarity'].lower() != 'common':
        stats_lines.append(f"**Rarity** {result['rarity']}")
    
    # Add stats section
    if stats_lines:
        embed.add_field(
            name="\u200b",
            value="\n".join(stats_lines),
            inline=False
        )
    
    # Add separator line (exactly like screenshot)
    embed.add_field(
        name="\u200b",
        value="─" * 45,
        inline=False
    )
    
    # Extract clean description by aggressively removing all stat information
    description_text = text
    
    # Remove everything before the actual description
    # Look for the start of the actual descriptive text
    sentences = description_text.split('.')
    clean_sentences = []
    
    for sentence in sentences:
        sentence = sentence.strip()
        # Skip sentences that are clearly stat information
        if any(stat_word in sentence.lower() for stat_word in [
            'price', 'bulk', 'hands', 'damage', 'category', 'group', 'level', 
            'rarity', 'traits', 'source', 'core rulebook', 'favored weapon',
            'type melee', 'critical specialization', 'specific magic weapons'
        ]):
            continue
        
        # Skip very short sentences (likely stat fragments)
        if len(sentence) < 20:
            continue
            
        # This looks like actual descriptive text
        if len(sentence) > 20 and not re.search(r'^\s*[A-Z][a-z]+\s+[A-Z]', sentence):
            clean_sentences.append(sentence)
    
    # Take the first few good sentences
    if clean_sentences:
        description_text = '. '.join(clean_sentences[:3]) + '.'
    else:
        # Fallback: show original text but truncated
        description_text = text[:500] + "..." if len(text) > 500 else text
    
    # Add main description (the paragraph of text)
    if description_text and len(description_text.strip()) > 10:
        if len(description_text) > 1000:
            description_text = description_text[:1000] + "..."
        embed.add_field(
            name="\u200b",
            value=description_text.strip(),
            inline=False
        )
    else:
        embed.add_field(
            name="\u200b",
            value="No description available.",
            inline=False
        )
    
    # Add source information at the bottom (clean format like screenshot)
    if result.get('source'):
        source_text = f"**{result['source']}**"
        embed.add_field(
            name="\u200b",
            value=source_text,
            inline=False
        )
    
    # Add other results if available (keep this information)
    if other_results:
        other_names = [r['name'] for r in other_results[:3]]
        embed.add_field(
            name="🔍 Other matches",
            value=", ".join(other_names) + ("..." if len(other_results) > 3 else ""),
            inline=False
        )
    
    # Footer credit to Archives of Nethys
    embed.set_footer(text="Data from Archives of Nethys")
    
    return embed

# --- BOT SETUP ---
class PF2eBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='!', intents=intents)
        
    async def setup_hook(self):
        """Called when the bot is starting up."""
        logger.info("Setting up slash commands...")
        try:
            synced = await self.tree.sync()
            logger.info(f"Synced {len(synced)} command(s)")
        except Exception as e:
            logger.error(f"Failed to sync commands: {e}")
    
    async def on_ready(self):
        """Called when the bot is ready."""
        logger.info(f'Bot is ready! Logged in as {self.user}')
        logger.info(f'Bot is in {len(self.guilds)} guilds')
        logger.info('-' * 50)

bot = PF2eBot()

# --- AUTOCOMPLETE FUNCTIONS ---
async def category_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> List[app_commands.Choice[str]]:
    """Autocomplete for category selection."""
    categories = ["All"] + SEARCH_CATEGORIES
    return [
        app_commands.Choice(name=category, value=category)
        for category in categories
        if current.lower() in category.lower()
    ][:25]  # Discord limits to 25 choices

async def search_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> List[app_commands.Choice[str]]:
    """Autocomplete for search queries based on popular items."""
    if len(current) < 2:
        return []
    
    # Popular search terms for quick access
    popular_terms = [
        "longsword", "healing potion", "fireball", "leather armor", "shield",
        "dagger", "shortbow", "chain mail", "rapier", "meteor hammer",
        "cure wounds", "magic missile", "detect magic", "mage armor"
    ]
    
    matching_terms = [
        term for term in popular_terms 
        if current.lower() in term.lower()
    ]
    
    return [
        app_commands.Choice(name=term.title(), value=term)
        for term in matching_terms
    ][:25]

# --- SLASH COMMANDS ---
@bot.tree.command(name="search", description="Search the Archives of Nethys for Pathfinder 2e content")
@app_commands.describe(
    query="What to search for (items, spells, feats, etc.)",
    category="Filter by category (optional)"
)
@app_commands.autocomplete(query=search_autocomplete, category=category_autocomplete)
async def search_command(
    interaction: discord.Interaction, 
    query: str,
    category: Optional[str] = None
):
    """Main search command with slash command interface."""
    
    # Defer response since search might take a moment
    await interaction.response.defer()
    
    try:
        # Perform search
        results = await search_aon_api(query, result_limit=3, category_filter=category)
        
        if not results:
            embed = discord.Embed(
                title="No Results Found",
                description=f"Sorry, I couldn't find anything matching **{query}**.\n\n"
                           f"Try:\n• Different search terms\n• Checking your spelling\n• Using a broader category",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed)
            return
        
        # Get best result
        best_result = results[0]
        
        # Create embed
        embed = create_embed_from_result(
            best_result, 
            other_results=results[1:] if len(results) > 1 else None
        )
        
        # Add search info to embed
        search_info = f"Search: **{query}**"
        if category and category != "All":
            search_info += f" • Category: **{category}**"
        
        embed.add_field(name="🔍 Search Info", value=search_info, inline=False)
        
        await interaction.followup.send(embed=embed)
        logger.info(f"Search completed for '{query}' by {interaction.user}")
        
    except Exception as e:
        logger.error(f"Error in search command: {e}")
        embed = discord.Embed(
            title="Search Error",
            description="An error occurred while searching. Please try again.",
            color=discord.Color.red()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="help", description="Show help information for the bot")
async def help_command(interaction: discord.Interaction):
    """Show bot help information."""
    
    embed = discord.Embed(
        title="🏰 Archives of Nethys Bot Help",
        description="Search for Pathfinder 2e content with modern slash commands!",
        color=discord.Color.blue()
    )
    
    embed.add_field(
        name="🔍 /search",
        value="Search for any PF2e content\n"
              "• **query**: What to search for\n"
              "• **category**: Filter by type (optional)",
        inline=False
    )
    
    embed.add_field(
        name="📚 /help",
        value="Show this help message",
        inline=False
    )
    
    embed.add_field(
        name="💡 Tips",
        value="• Use autocomplete for faster searches\n"
              "• Try different search terms if you don't find what you need\n"
              "• Category filters help narrow down results",
        inline=False
    )
    
    embed.set_footer(text="Data from Archives of Nethys")
    
    await interaction.response.send_message(embed=embed)

# --- ERROR HANDLING ---
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    """Handle slash command errors."""
    
    if isinstance(error, app_commands.CommandOnCooldown):
        await interaction.response.send_message(
            f"Command is on cooldown. Try again in {error.retry_after:.2f} seconds.",
            ephemeral=True
        )
    else:
        logger.error(f"Slash command error: {error}")
        
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "An error occurred while processing your command.",
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                "An error occurred while processing your command.",
                ephemeral=True
            )

# --- RUN THE BOT ---
if __name__ == "__main__":
    try:
        bot.run(TOKEN)
    except discord.errors.LoginFailure:
        logger.error("Invalid token provided")
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
