# main.py
# A Discord bot that searches the Archives of Nethys using their Elasticsearch API
# This is much more reliable than web scraping!

import discord
import os
import requests
import json
import logging

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

COMMAND_PREFIX = "!aon"

# Archives of Nethys Elasticsearch API
AON_API_BASE = "https://elasticsearch.aonprd.com/aon/_search"
AON_WEB_BASE = "https://2e.aonprd.com/"

# --- BOT SETUP ---
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

def search_aon_api(query: str, result_limit: int = 5):
    """
    Search Archives of Nethys using their Elasticsearch API.
    
    Args:
        query (str): Search term
        result_limit (int): Number of results to return
    
    Returns:
        list: List of search results
    """
    logger.info(f"Searching API for: {query}")
    
    try:
        # Elasticsearch query structure
        search_body = {
            "query": {
                "bool": {
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
            },
            "size": result_limit,
            "_source": ["name", "type", "url", "text", "level", "price", "category", "source"],
            "sort": [
                {"_score": {"order": "desc"}},
                {"name.keyword": {"order": "asc"}}
            ]
        }
        
        headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'DiscordBot-AON-Search/1.0'
        }
        
        response = requests.post(
            AON_API_BASE,
            headers=headers,
            data=json.dumps(search_body),
            timeout=10
        )
        
        response.raise_for_status()
        data = response.json()
        
        results = []
        if 'hits' in data and 'hits' in data['hits']:
            for hit in data['hits']['hits']:
                source = hit['_source']
                
                # Build the full URL
                if 'url' in source and source['url']:
                    if source['url'].startswith('http'):
                        full_url = source['url']
                    else:
                        full_url = AON_WEB_BASE + source['url']
                else:
                    full_url = None
                
                result = {
                    'name': source.get('name', 'Unknown'),
                    'type': source.get('type', 'Unknown'),
                    'url': full_url,
                    'text': source.get('text', ''),
                    'level': source.get('level'),
                    'price': source.get('price'),
                    'category': source.get('category'),
                    'source': source.get('source'),
                    'score': hit['_score']
                }
                results.append(result)
        
        logger.info(f"Found {len(results)} results")
        return results
        
    except requests.exceptions.RequestException as e:
        logger.error(f"API request failed: {e}")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse API response: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error in API search: {e}")
        return None

def create_embed_from_result(result):
    """Create a Discord embed from a search result."""
    
    # Clean up the text content
    text = result.get('text', '').strip()
    if len(text) > 4000:
        text = text[:4000] + "\n\n... (truncated)"
    
    # Create embed
    embed = discord.Embed(
        title=result['name'],
        url=result['url'] if result['url'] else None,
        description=text if text else "No description available.",
        color=discord.Color.dark_red()
    )
    
    # Add fields for additional info
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
    
    embed.set_footer(text="Data from Archives of Nethys • Powered by Elasticsearch API")
    
    return embed

# --- DISCORD EVENTS ---

@client.event
async def on_ready():
    """Called when the bot successfully logs in."""
    logger.info(f'Bot is ready and logged in as {client.user}')
    logger.info(f'Bot is in {len(client.guilds)} guilds')
    logger.info('-----------------------------------------')

@client.event
async def on_message(message):
    """Called every time a message is sent in a channel the bot can see."""
    if message.author == client.user:
        return

    # Handle search command
    if message.content.startswith(COMMAND_PREFIX + " "):
        query = message.content[len(COMMAND_PREFIX)+1:].strip()

        if not query:
            await message.channel.send(f"Please provide an item to search for. Usage: `{COMMAND_PREFIX} <item name>`")
            return

        logger.info(f"Processing search request for: {query}")
        
        try:
            # Send processing message
            processing_message = await message.channel.send(f"🔍 Searching for `{query}` in the Archives...")
            
            # Perform the search
            results = search_aon_api(query, result_limit=3)
            
            # Delete processing message
            try:
                await processing_message.delete()
            except discord.errors.NotFound:
                pass
            
            if results and len(results) > 0:
                # Send the best result
                best_result = results[0]
                embed = create_embed_from_result(best_result)
                
                # If there are multiple results, mention them
                if len(results) > 1:
                    other_results = [r['name'] for r in results[1:]]
                    embed.add_field(
                        name="Other matches", 
                        value=", ".join(other_results[:3]) + ("..." if len(other_results) > 3 else ""),
                        inline=False
                    )
                
                await message.channel.send(embed=embed)
                logger.info(f"Successfully sent result for: {query}")
                
            else:
                await message.channel.send(f"Sorry, I couldn't find anything matching `{query}`. Try different terms or check your spelling.")
                
        except discord.errors.Forbidden:
            logger.error("Bot doesn't have permission to send messages in this channel")
        except Exception as e:
            logger.error(f"Error processing search: {e}")
            try:
                await processing_message.delete()
            except:
                pass
            await message.channel.send(f"An error occurred while searching for `{query}`. Please try again later.")

    # Test command
    elif message.content == f"{COMMAND_PREFIX}test":
        await message.channel.send("Bot is working! 🤖 Using the new API-based search.")
    
    # Help command
    elif message.content == f"{COMMAND_PREFIX}help":
        help_embed = discord.Embed(
            title="Archives of Nethys Bot Help",
            description="Search for Pathfinder 2e content from the Archives of Nethys",
            color=discord.Color.blue()
        )
        help_embed.add_field(
            name="Commands",
            value=f"`{COMMAND_PREFIX} <search term>` - Search for items, spells, creatures, etc.\n"
                  f"`{COMMAND_PREFIX}test` - Test if the bot is working\n"
                  f"`{COMMAND_PREFIX}help` - Show this help message",
            inline=False
        )
        help_embed.add_field(
            name="Examples",
            value=f"`{COMMAND_PREFIX} healing potion`\n"
                  f"`{COMMAND_PREFIX} fireball`\n"
                  f"`{COMMAND_PREFIX} goblin`",
            inline=False
        )
        await message.channel.send(embed=help_embed)

@client.event
async def on_error(event, *args, **kwargs):
    """Handle errors that occur during events."""
    logger.error(f"An error occurred in event {event}", exc_info=True)

# --- RUN THE BOT ---
if __name__ == "__main__":
    try:
        client.run(TOKEN)
    except discord.errors.LoginFailure:
        logger.error("Invalid token provided")
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
