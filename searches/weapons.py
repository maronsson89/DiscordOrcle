import aiohttp
import re
from html import unescape
import logging
import asyncio
from urllib.parse import quote, quote_plus

async def search_weapon(weapon_name):
    """Search for a weapon on Archives of Nethys and return Discord embed"""
    
    url = "https://elasticsearch.aonprd.com/aon/_search"
    timeout = aiohttp.ClientTimeout(total=10)
    
    # Try exact match first
    query = {
        "query": {
            "bool": {
                "must": [
                    {"term": {"category": "weapon"}},
                    {"term": {"name.keyword": weapon_name.lower()}}
                ]
            }
        },
        "size": 1
    }
    
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=query) as response:
                response.raise_for_status()
                data = await response.json()
            
            # If no exact match, try fuzzy search
            if not data.get("hits", {}).get("hits"):
                query = {
                    "query": {
                        "bool": {
                            "must": [
                                {"term": {"category": "weapon"}},
                                {"match": {"name": weapon_name}}
                            ]
                        }
                    },
                    "size": 1
                }
                async with session.post(url, json=query) as response:
                    response.raise_for_status()
                    data = await response.json()
        
        # Check if we got results
        hits = data.get("hits", {}).get("hits", [])
        if not hits:
            return {
                "title": "Weapon Not Found",
                "description": f"No weapon matching '{weapon_name}' found on the Archives of Nethys.",
                "color": 0xFFAD00 # Amber
            }
        
        weapon = hits[0]["_source"]

        # Assume the data is unstructured and display it directly.
        description = clean_html(weapon.get("text", "No description available."))

        # Create a link to the Archives of Nethys page
        aon_id = weapon.get('aonId')
        if aon_id:
            link = f"https://2e.aonprd.com/Weapons.aspx?ID={aon_id}"
        else:
            # Fallback to a search link if no ID is present
            encoded_name = quote_plus(weapon.get('name', weapon_name))
            link = f"https://2e.aonprd.com/Search.aspx?q={encoded_name}"
        
        description += f"\n\n[View on Archives of Nethys]({link})"

        # Build a simple embed with the available data
        embed = {
            "title": f"**{weapon.get('name', 'Unknown Weapon')}**",
            "description": description,
            "footer": {"text": f"Source: {weapon.get('source', 'N/A')} | Archives of Nethys"}
        }

        sanitized_name = re.sub(r'[^a-zA-Z0-9]', '', weapon.get('name', 'Fallback'))
        embed["thumbnail"] = {"url": f"https://2e.aonprd.com/Images/Weapons/{sanitized_name}.webp"}

        return embed
        
    except asyncio.TimeoutError:
        logging.warning("AON API request timed out.")
        return {
            "title": "Error: Request Timed Out",
            "description": "The request to the Archives of Nethys took too long to respond. The site may be slow or down.",
            "color": 0xFFAD00 # Amber
        }
    except aiohttp.ClientResponseError as e:
        logging.error(f"AON API request failed: {e}")
        return {
            "title": "Error: Archives of Nethys API",
            "description": f"The API request to Archives of Nethys failed with status: {e.status}",
            "color": 0xFF0000
        }
    except Exception as e:
        logging.exception("An unexpected error occurred in search_weapon")
        return {
            "title": "Error",
            "description": f"An unexpected error occurred: `{type(e).__name__}: {e}`",
            "color": 0xFF0000
        }

def clean_html(text):
    """Remove HTML tags and unescape entities"""
    # Convert <br> to newlines
    text = text.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    # Remove all other HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    # Unescape HTML entities
    text = unescape(text)
    return text.strip()
