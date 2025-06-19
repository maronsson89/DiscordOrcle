# main.py - PF2e Discord Bot with Slash Commands
# v6 - Modern slash commands with autocomplete and better UX

import discord
from discord.ext import commands
from discord import app_commands
import os
import aiohttp
import json
import logging
import re
import asyncio
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

# Foundry VTT PF2e Equipment Images Database
FOUNDRY_IMAGE_MAP = {
    "meteor hammer": "systems/pf2e/icons/equipment/weapons/meteor-hammer.webp",
    "healing potion": "systems/pf2e/icons/equipment/consumables/healing-potion.webp",
    "minor healing potion": "systems/pf2e/icons/equipment/consumables/healing-potion.webp",
    "longsword": "systems/pf2e/icons/equipment/weapons/longsword.webp",
    "rope dart": "systems/pf2e/icons/equipment/weapons/rope-dart.webp",
    "plate armor": "systems/pf2e/icons/equipment/armor/plate-armor.webp",
    "leather armor": "systems/pf2e/icons/equipment/armor/leather-armor.webp",
    "chain mail": "systems/pf2e/icons/equipment/armor/chain-mail.webp",
    "shortbow": "systems/pf2e/icons/equipment/weapons/shortbow.webp",
    "dagger": "systems/pf2e/icons/equipment/weapons/dagger.webp",
    "rapier": "systems/pf2e/icons/equipment/weapons/rapier.webp",
    "shield": "systems/pf2e/icons/equipment/shields/wooden-shield.webp",
}

FOUNDRY_IMAGE_BASE = "https://your-cdn.com/pf2e-images/"

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

def get_foundry_image(item_name):
    """Get equipment image from Foundry VTT database."""
    normalized_name = item_name.lower().strip()
    
    if normalized_name in FOUNDRY_IMAGE_MAP:
        image_path = FOUNDRY_IMAGE_MAP[normalized_name]
        return f"{FOUNDRY_IMAGE_BASE}{image_path}"
    
    # Try partial matches
    for key, image_path in FOUNDRY_IMAGE_MAP.items():
        if key in normalized_name or normalized_name in key:
            return f"{FOUNDRY_IMAGE_BASE}{image_path}"
    
    return None

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
                    'User-Agent': 'DiscordBot-AON-Search/2.0'
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

def create_embed_from_result(result, image_url=None, other_results=None):
    """Create a Discord embed from a search result."""
    
    color = discord.Color.gold() if image_url else discord.Color.dark_red()
    
    embed = discord.Embed(
        title=result['name'],
        url=result['url'] if result['url'] else None,
        color=color
    )
    
    # Add rarity to title if not common
    if result.get('rarity') and result['rarity'].lower() != 'common':
        embed.title = f"{result['name']} ({result['rarity']})"
    
    # Clean description
    description = clean_text(result.get('text', ''))
    if len(description) > 4000:
        description = description[:4000] + "\n\n... (truncated)"
    
    embed.description = description if description else "No description available."
    
    # Add info fields
    if result.get('type'):
        embed.add_field(name="Type", value=result['type'], inline=True)
    
    if result.get('level'):
        embed.add_field(name="Level", value=str(result['level']), inline=True)
    
    if result.get('price'):
        embed.add_field(name="Price", value=result['price'], inline=True)
    
    if result.get('category'):
        embed.add_field(name="Category", value=result['category'], inline=True)
    
    if result.get('source'):
        embed.add_field(name="Source", value=result['source'], inline=True)
    
    # Add spacing field if odd number of fields
    field_count = sum(1 for x in [result.get('type'), result.get('level'), result.get('price'), 
                                  result.get('category'), result.get('source')] if x)
    if field_count % 3 == 1:
        embed.add_field(name="\u200b", value="\u200b", inline=True)
    elif field_count % 3 == 2:
        embed.add_field(name="\u200b", value="\u200b", inline=True)
    
    # Add other results
    if other_results:
        other_names = [r['name'] for r in other_results[:3]]
        embed.add_field(
            name="🔍 Other matches",
            value=", ".join(other_names) + ("..." if len(other_results) > 3 else ""),
            inline=False
        )
    
    # Add image
    if image_url:
        embed.set_thumbnail(url=image_url)
    
    # Footer
    footer_text = "Archives of Nethys"
    if image_url:
        footer_text += " • Images from Foundry VTT PF2e"
    
    embed.set_footer(text=footer_text)
    
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
        logger.info(f'Foundry image database: {len(FOUNDRY_IMAGE_MAP)} items')
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
    category="Filter by category (optional)",
    include_image="Try to include official artwork when available"
)
@app_commands.autocomplete(query=search_autocomplete, category=category_autocomplete)
async def search_command(
    interaction: discord.Interaction, 
    query: str,
    category: Optional[str] = None,
    include_image: bool = True
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
        
        # Check for image if requested
        image_url = None
        if include_image:
            image_url = get_foundry_image(best_result['name'])
        
        # Create embed
        embed = create_embed_from_result(
            best_result, 
            image_url=image_url,
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

@bot.tree.command(name="random", description="Get a random item from the Archives of Nethys")
@app_commands.describe(category="Filter by category (optional)")
@app_commands.autocomplete(category=category_autocomplete)
async def random_command(
    interaction: discord.Interaction,
    category: Optional[str] = None
):
    """Get a random item from the archives."""
    
    await interaction.response.defer()
    
    try:
        # Use a random search to get diverse results
        import random
        random_terms = ["sword", "potion", "armor", "spell", "ring", "staff", "bow", "shield"]
        random_query = random.choice(random_terms)
        
        results = await search_aon_api(random_query, result_limit=10, category_filter=category)
        
        if not results:
            embed = discord.Embed(
                title="No Random Item Found",
                description="Couldn't find a random item. Try again!",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed)
            return
        
        # Pick a random result
        random_result = random.choice(results)
        image_url = get_foundry_image(random_result['name'])
        
        embed = create_embed_from_result(random_result, image_url=image_url)
        embed.add_field(name="🎲 Random Item", value="Here's something interesting!", inline=False)
        
        await interaction.followup.send(embed=embed)
        
    except Exception as e:
        logger.error(f"Error in random command: {e}")
        embed = discord.Embed(
            title="Random Error",
            description="An error occurred while finding a random item.",
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
              "• **category**: Filter by type (optional)\n"
              "• **include_image**: Show artwork when available",
        inline=False
    )
    
    embed.add_field(
        name="🎲 /random",
        value="Get a random item from the archives\n"
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
    
    embed.add_field(
        name="🎨 Features",
        value=f"• **{len(FOUNDRY_IMAGE_MAP)}** items with official artwork\n"
              "• Smart search with fuzzy matching\n"
              "• Fast results with caching\n"
              "• Category filtering",
        inline=False
    )
    
    embed.set_footer(text="Data from Archives of Nethys • Images from Foundry VTT PF2e")
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="credits", description="Show credits and legal information")
async def credits_command(interaction: discord.Interaction):
    """Show credits and attribution."""
    
    embed = discord.Embed(
        title="📜 Credits & Attribution",
        description="This bot uses content from multiple sources",
        color=discord.Color.green()
    )
    
    embed.add_field(
        name="📖 Game Data",
        value="[Archives of Nethys](https://2e.aonprd.com/)\n"
              "Official Pathfinder 2e SRD content",
        inline=False
    )
    
    embed.add_field(
        name="🎨 Artwork",
        value="Foundry VTT PF2e System (Apache License)\n"
              "Official Paizo artwork with permission",
        inline=False
    )
    
    embed.add_field(
        name="⚖️ Legal Notice",
        value="This bot uses trademarks and/or copyrights owned by Paizo Inc., "
              "used under Paizo's Community Use Policy.\n"
              "[paizo.com/communityuse](https://paizo.com/communityuse)",
        inline=False
    )
    
    embed.add_field(
        name="🔧 Bot Info",
        value="Built with discord.py\n"
              "Slash commands for modern Discord experience",
        inline=False
    )
    
    await interaction.response.send_message(embed=embed)

# --- CONTEXT MENU COMMANDS ---
@bot.tree.context_menu(name="Search Archives of Nethys")
async def context_search(interaction: discord.Interaction, message: discord.Message):
    """Context menu command to search selected text."""
    
    # Extract search query from message content
    query = message.content.strip()
    
    # Limit query length
    if len(query) > 100:
        query = query[:100]
    
    if not query:
        await interaction.response.send_message(
            "No text found to search for!", 
            ephemeral=True
        )
        return
    
    await interaction.response.defer(ephemeral=True)
    
    try:
        results = await search_aon_api(query, result_limit=1)
        
        if results:
            result = results[0]
            image_url = get_foundry_image(result['name'])
            embed = create_embed_from_result(result, image_url=image_url)
            embed.add_field(
                name="🔍 Context Search", 
                value=f"Searched for: **{query}**", 
                inline=False
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.followup.send(
                f"No results found for: **{query}**", 
                ephemeral=True
            )
            
    except Exception as e:
        logger.error(f"Error in context search: {e}")
        await interaction.followup.send(
            "An error occurred during the search.", 
            ephemeral=True
        )

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
