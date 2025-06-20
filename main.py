# main.py - Simple PF2e Discord Bot with Slash Commands (Plain Text Format)

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

def create_formatted_text_from_result(result, other_results=None):
    """Create formatted Discord text from a search result matching the exact structure."""
    
    # Get the raw text for parsing
    text = clean_text(result.get('text', ''))
    
    # Parse traits and weapon stats
    traits = parse_traits_from_text(text)
    weapon_stats = parse_weapon_stats(text, result)
    
    # Start building the formatted text
    lines = []
    
    # Line 1: ****Item****
    lines.append("****Item****")
    
    # Line 2: **[Weapon Name]**
    weapon_name = result['name']
    if result.get('rarity') and result['rarity'].lower() != 'common':
        weapon_name += f" ({result['rarity']})"
    lines.append(f"**{weapon_name}**")
    
    # Line 3: Traits in brackets
    if traits:
        trait_string = "".join([f"［ {trait} ］" for trait in traits])
        lines.append(trait_string)
    else:
        lines.append("None")
    
    # Line 4: Price
    price = result.get('price', 'Unknown')
    lines.append(f"**Price** {price}")
    
    # Line 5: Bulk and Hands
    bulk = weapon_stats.get('bulk', 'Unknown')
    hands = weapon_stats.get('hands', '1')
    lines.append(f"**Bulk** {bulk}; **Hands** {hands}")
    
    # Line 6: Damage
    damage = weapon_stats.get('damage', 'Unknown')
    lines.append(f"**Damage** {damage}")
    
    # Line 7: Category and Group
    category_parts = []
    if result.get('category'):
        category = result['category']
        if category.lower() != 'weapon':
            category_parts.append(category)
        else:
            if 'martial' in text.lower():
                category_parts.append('martial melee weapon')
            elif 'simple' in text.lower():
                category_parts.append('simple melee weapon')
            else:
                category_parts.append('melee weapon')
    else:
        category_parts.append('melee weapon')
    
    group = weapon_stats.get('group', 'unknown')
    lines.append(f"**Category** {'; '.join(category_parts)}; **Group** {group}")
    
    # Line 8: Horizontal divider
    lines.append("⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯")
    
    # Line 9: Description
    description = extract_main_description(text)
    lines.append(description)
    
    # Line 10: Blank line
    lines.append("")
    
    # Line 11: Source (simplified to avoid too many links)
    source = result.get('source', 'Unknown')
    lines.append(f"📘 **Source:** {source}")
    
    # Line 12: Blank line
    lines.append("")
    
    # Line 13: Favored Weapon header
    lines.append("****Favored Weapon of****")
    
    # Line 14: Favored weapon list
    favored_deities = extract_favored_weapon_info(text)
    lines.append(favored_deities if favored_deities else "None")
    
    # Line 15: Blank line
    lines.append("")
    
    # Line 16: Critical Specialization header
    group_name = weapon_stats.get('group', 'Unknown').title()
    lines.append(f"****Critical Specialization Effect ({group_name} Group):****")
    
    # Line 17: Critical effect text
    crit_effect = get_critical_specialization_effect(weapon_stats.get('group', ''))
    lines.append(crit_effect)
    
    # Line 18: Blank line
    lines.append("")
    
    # Line 19: Specific Magic weapons header
    lines.append(f"****Specific Magic {result['name']}s:****")
    
    # Line 20: Magic weapons list
    magic_weapons = extract_magic_weapon_info(text)
    lines.append(magic_weapons if magic_weapons else "None")
    
    # Line 21: Blank line
    lines.append("")
    
    # Line 22: Footer (simplified)
    lines.append("🔗 Data from Archives of Nethys")
    
    return "\n".join(lines)

def extract_main_description(text):
    """Extract the main descriptive paragraph."""
    # Look for descriptive sentences that aren't stat blocks
    sentences = text.split('.')
    good_sentences = []
    
    for sentence in sentences:
        sentence = sentence.strip()
        
        # Skip stat-heavy sentences
        if any(keyword in sentence.lower() for keyword in [
            'source', 'favored weapon', 'type melee', 'critical specialization',
            'specific magic', 'price', 'bulk', 'hands', 'damage', 'category'
        ]):
            continue
            
        # Skip very short sentences
        if len(sentence) < 15:
            continue
            
        # Look for descriptive content
        if any(desc_word in sentence.lower() for desc_word in [
            'blade', 'weapon', 'sword', 'known as', 'feet', 'length', 'heavy',
            'edge', 'consist', 'made', 'used', 'designed'
        ]):
            good_sentences.append(sentence)
            if len(good_sentences) >= 2:  # Limit to 1-2 sentences
                break
    
    if good_sentences:
        return '. '.join(good_sentences) + '.'
    
    # Fallback
    return "A martial weapon used in combat."

def extract_favored_weapon_info(text):
    """Extract favored weapon information."""
    favored_match = re.search(r'favored weapon[^.]*?([A-Z][^.]*)', text, re.IGNORECASE)
    if favored_match:
        favored_text = favored_match.group(1).strip()
        # Clean up the list
        favored_text = re.sub(r'\s+', ' ', favored_text)
        return favored_text
    return None

def extract_magic_weapon_info(text):
    """Extract specific magic weapons information."""
    magic_match = re.search(r'specific magic[^.]*?([A-Z][^.]*)', text, re.IGNORECASE)
    if magic_match:
        magic_text = magic_match.group(1).strip()
        # Clean up the list
        magic_text = re.sub(r'\s+', ' ', magic_text)
        return magic_text
    return None

def get_critical_specialization_effect(weapon_group):
    """Get the critical specialization effect for a weapon group."""
    effects = {
        'sword': "The target is made off-balance by your attack, becoming **flat-footed** until the start of your next turn.",
        'axe': "Choose one creature adjacent to the initial target and within reach. If its AC is lower than your attack roll result for the critical hit, you deal damage to that creature equal to the result of the weapon damage die you rolled (including extra dice for its *striking* rune, if any). This amount isn't doubled, and no bonuses or other additional dice apply to this damage.",
        'bow': "If the target of the critical hit is adjacent to a surface, you pin the target to that surface by driving the missile deep into the target and the surface. The target is **immobilized** and must spend an Interact action to attempt a DC 10 Athletics check to pull the missile free; it can't move from its space until it succeeds. The creature doesn't become stuck if it is incorporeal, is liquid (like a water elemental or some oozes), or could otherwise escape without effort.",
        'club': "You knock the target away from you up to 10 feet (you choose the distance). This is forced movement.",
        'dart': "Your target takes 1d6 persistent bleed damage. You gain an item bonus to this bleed damage equal to the weapon's item bonus to attack rolls.",
        'flail': "The target is knocked **prone**.",
        'hammer': "The target is knocked **prone**.",
        'knife': "The target takes 1d6 persistent bleed damage. You gain an item bonus to this bleed damage equal to the weapon's item bonus to attack rolls.",
        'pick': "The weapon viciously pierces the target, who takes 2 additional damage per weapon damage die.",
        'polearm': "The target is moved 5 feet in a direction of your choice. This is forced movement.",
        'shield': "You knock the target back from you 5 feet. This is forced movement.",
        'sling': "The target must succeed at a Fortitude save against your class DC or be **stunned 1**.",
        'spear': "The weapon pierces the target, weakening its attacks. The target takes a –2 circumstance penalty to damage rolls for 1 round.",
    }
    
    return effects.get(weapon_group.lower(), "No specific effect for this weapon group.")

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
            await interaction.followup.send(
                f"**No Results Found**\n\n"
                f"Sorry, I couldn't find anything matching **{query}**.\n\n"
                f"Try:\n• Different search terms\n• Checking your spelling\n• Using a broader category"
            )
            return
        
        # Get best result
        best_result = results[0]
        
        # Create formatted text
        formatted_text = create_formatted_text_from_result(
            best_result, 
            other_results=results[1:] if len(results) > 1 else None
        )
        
        # Check message length and split if needed
        if len(formatted_text) > 2000:
            # Split the message into chunks
            chunks = []
            lines = formatted_text.split('\n')
            current_chunk = ""
            
            for line in lines:
                if len(current_chunk + line + '\n') > 2000:
                    chunks.append(current_chunk.strip())
                    current_chunk = line + '\n'
                else:
                    current_chunk += line + '\n'
            
            if current_chunk.strip():
                chunks.append(current_chunk.strip())
            
            # Send first chunk
            await interaction.followup.send(chunks[0])
            
            # Send remaining chunks
            for chunk in chunks[1:]:
                await interaction.followup.send(chunk)
        else:
            # Send the formatted text
            await interaction.followup.send(formatted_text)
        
        logger.info(f"Search completed for '{query}' by {interaction.user}")
        
    except Exception as e:
        logger.error(f"Error in search command: {e}")
        await interaction.followup.send(
            "**Search Error**\n\nAn error occurred while searching. Please try again.",
            ephemeral=True
        )

@bot.tree.command(name="help", description="Show help information for the bot")
async def help_command(interaction: discord.Interaction):
    """Show bot help information."""
    
    help_text = """**🏰 Archives of Nethys Bot Help**

Search for Pathfinder 2e content with modern slash commands!

**🔍 /search**
Search for any PF2e content
• **query**: What to search for
• **category**: Filter by type (optional)

**📚 /help**
Show this help message

**💡 Tips**
• Use autocomplete for faster searches
• Try different search terms if you don't find what you need
• Category filters help narrow down results

🔗 Data from Archives of Nethys"""
    
    await interaction.response.send_message(help_text)

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
