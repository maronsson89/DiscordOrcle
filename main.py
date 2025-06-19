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
    # Look for trait patterns in parentheses or specific formatting
    trait_patterns = [
        r'\bbackswing\b', r'\bdisarm\b', r'\breach\b', r'\btrip\b', r'\bfinesse\b',
        r'\bagile\b', r'\bdeadly\b', r'\bfatal\b', r'\bversatile\b', r'\bparry\b',
        r'\btwo-hand\b', r'\bthrown\b', r'\branged\b', r'\bvolley\b'
    ]
    
    for pattern in trait_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            trait_name = pattern.replace(r'\b', '').replace(r'\\', '')
            traits.append(trait_name.title())
    
    return traits

def parse_weapon_stats(text, result):
    """Parse weapon-specific stats from text."""
    stats = {}
    
    # Extract damage (look for patterns like "1d8", "1d6+1", etc.)
    damage_match = re.search(r'(\d+d\d+(?:\+\d+)?)\s*(\w+)?', text, re.IGNORECASE)
    if damage_match:
        damage_die = damage_match.group(1)
        damage_type = damage_match.group(2) or "bludgeoning"
        stats['damage'] = f"{damage_die} {damage_type.lower()}"
    
    # Extract bulk (look for "Bulk" followed by number or L)
    bulk_match = re.search(r'bulk\s*([0-9]+|L|-)', text, re.IGNORECASE)
    if bulk_match:
        stats['bulk'] = bulk_match.group(1)
    
    # Extract hands (look for "Hands" or common patterns)
    hands_match = re.search(r'hands?\s*(\d+)', text, re.IGNORECASE)
    if hands_match:
        stats['hands'] = hands_match.group(1)
    elif 'two-hand' in text.lower():
        stats['hands'] = '2'
    elif 'one-hand' in text.lower():
        stats['hands'] = '1'
    
    # Try to extract group information
    group_match = re.search(r'group\s+(\w+)', text, re.IGNORECASE)
    if group_match:
        stats['group'] = group_match.group(1).lower()
    
    return stats

def create_embed_from_result(result, other_results=None):
    """Create a Discord embed from a search result matching the exact style."""
    
    embed = discord.Embed(
        color=discord.Color.dark_grey()
    )
    
    # Set the type as the author (top small text)
    if result.get('type'):
        embed.set_author(name=result['type'])
    
    # Main title with rarity
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
    
    # Build the stats section exactly like the image
    stats_lines = []
    
    # Add traits in brackets if found
    if traits:
        trait_string = "  ".join([f"[ {trait} ]" for trait in traits])
        stats_lines.append(trait_string)
    
    # Add level (important for items, spells, feats)
    if result.get('level'):
        stats_lines.append(f"**Level** {result['level']}")
    
    # Add price
    if result.get('price'):
        stats_lines.append(f"**Price** {result['price']}")
    
    # Add bulk and hands on same line if available (weapon-specific)
    bulk_hands_parts = []
    if weapon_stats.get('bulk'):
        bulk_hands_parts.append(f"Bulk {weapon_stats['bulk']}")
    if weapon_stats.get('hands'):
        bulk_hands_parts.append(f"Hands {weapon_stats['hands']}")
    if bulk_hands_parts:
        stats_lines.append("**" + "; ".join(bulk_hands_parts) + "**")
    
    # Add damage (weapon-specific)
    if weapon_stats.get('damage'):
        stats_lines.append(f"**Damage** {weapon_stats['damage']}")
    
    # Add category and group
    category_parts = []
    if result.get('category'):
        category_parts.append(result['category'])
    if weapon_stats.get('group'):
        category_parts.append(f"Group {weapon_stats['group']}")
    if category_parts:
        stats_lines.append("**Category** " + "; ".join(category_parts))
    
    # Add type as a separate field if it's not already shown and is important
    item_type = result.get('type')
    if item_type and item_type.lower() not in ['equipment', 'item']:
        stats_lines.append(f"**Type** {item_type}")
    
    # Add rarity as a separate line if it's not common
    if result.get('rarity') and result['rarity'].lower() != 'common':
        stats_lines.append(f"**Rarity** {result['rarity']}")
    
    # Add stats section
    if stats_lines:
        embed.add_field(
            name="\u200b",
            value="\n".join(stats_lines),
            inline=False
        )
    
    # Add separator line
    embed.add_field(
        name="\u200b",
        value="─" * 45,
        inline=False
    )
    
    # Extract main description (usually the paragraph after stats)
    # Try to find the descriptive text by removing stat lines
    description_text = text
    
    # Remove common stat patterns to get clean description
    description_text = re.sub(r'price\s*:?\s*\d+\s*\w*', '', description_text, flags=re.IGNORECASE)
    description_text = re.sub(r'bulk\s*:?\s*[0-9L-]+', '', description_text, flags=re.IGNORECASE)
    description_text = re.sub(r'hands?\s*:?\s*\d+', '', description_text, flags=re.IGNORECASE)
    description_text = re.sub(r'damage\s*:?\s*\d+d\d+\s*\w+', '', description_text, flags=re.IGNORECASE)
    description_text = re.sub(r'category\s*:?[^.]*', '', description_text, flags=re.IGNORECASE)
    description_text = re.sub(r'group\s*:?\s*\w+', '', description_text, flags=re.IGNORECASE)
    description_text = re.sub(r'level\s*:?\s*\d+', '', description_text, flags=re.IGNORECASE)
    description_text = re.sub(r'rarity\s*:?\s*\w+', '', description_text, flags=re.IGNORECASE)
    description_text = description_text.strip()
    
    # Add main description
    if description_text:
        if len(description_text) > 1000:
            description_text = description_text[:1000] + "..."
        embed.add_field(
            name="\u200b",
            value=description_text,
            inline=False
        )
    else:
        # Fallback to "No description available" if we can't extract clean text
        embed.add_field(
            name="\u200b",
            value="No description available.",
            inline=False
        )
    
    # Add source information at the bottom
    if result.get('source'):
        source_text = f"**{result['source']}**"
        embed.add_field(
            name="\u200b",
            value=source_text,
            inline=False
        )
    
    # Add other results if available
    if other_results:
        other_names = [r['name'] for r in other_results[:3]]
        embed.add_field(
            name="🔍 Other matches",
            value=", ".join(other_names) + ("..." if len(other_results) > 3 else ""),
            inline=False
        )
    
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
