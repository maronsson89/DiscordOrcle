import aiohttp
import re
from html import unescape
import logging
import asyncio
import json
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
        
        # --- PART 1: The "Webservice" - Displaying the raw data ---
        raw_data_string = json.dumps(weapon, indent=2)
        description = f"**SUCCESS!** The 'webservice' part is working. Here is the raw data it fetched.\n\nPlease copy the text in the code block and paste it back to me so we can build the 'organizer'.\n\n```json\n{raw_data_string}\n```"
        if len(description) > 4000:
             description = description[:4000] + "...```"

        embed = {
            "title": f"Raw Data for: {weapon.get('name', 'Unknown')}",
            "description": description,
            "color": 0x00FF00 # Green
        }
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
        # If this part fails, the "webservice" itself has an issue.
        return {"title": "PART 1 FAILED: 'Webservice' Error", "description": f"Could not fetch data from Archives of Nethys.\n`{type(e).__name__}: {e}`", "color": 0xFF0000}

def clean_html(text):
    """Remove HTML tags and unescape entities"""
    # Convert <br> to newlines
    text = text.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    # Remove all other HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    # Unescape HTML entities
    text = unescape(text)
    return text.strip()
