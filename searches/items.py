import aiohttp
import re
from html import unescape
import logging

async def search_item(item_name):
    """Search for an item on Archives of Nethys and return Discord embed"""
    
    url = "https://elasticsearch.aonprd.com/aon/_search"
    timeout = aiohttp.ClientTimeout(total=10) # 10 second timeout
    
    # Try exact match first
    query = {
        "query": {
            "bool": {
                "must": [
                    {"term": {"category": "equipment"}},
                    {"term": {"name.keyword": item_name.lower()}}
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
                                {"term": {"category": "equipment"}},
                                {"match": {"name": item_name}}
                            ]
                        }
                    },
                    "size": 1
                }
                async with session.post(url, json=query) as response:
                    response.raise_for_status()
                    data = await response.json()
        
        hits = data.get("hits", {}).get("hits", [])
        if not hits:
            return {
                "title": "Item Not Found",
                "description": f"No item matching '{item_name}' found on the Archives of Nethys.",
                "color": 0xFFAD00 # Amber
            }
        
        item = hits[0]["_source"]
        
        # Extract description
        text = item.get("text", "")
        description = ""
        if "---" in text:
            description = clean_html(text.split("---", 1)[0].strip())
        else:
            description = clean_html(text)
        
        # Build embed
        embed = {
            "title": f"**{item['name']}**",
            "url": f"https://2e.aonprd.com/Equipment.aspx?ID={item.get('aonId', '')}",
            "description": description,
            "fields": []
        }
        
        # Properties
        properties = {
            "name": "**Properties**",
            "value": f"**Price**: {item.get('price', 'N/A')}\n**Level**: {item.get('level', 0)}\n**Bulk**: {item.get('bulk', 'N/A')}",
            "inline": True
        }
        embed["fields"].append(properties)
        
        # Usage
        usage = {
            "name": "**Usage**",
            "value": f"**Worn**: {item.get('usage', 'N/A')}\n**Hands**: {item.get('hands', 'N/A')}",
            "inline": True
        }
        embed["fields"].append(usage)
        
        # Traits
        traits_data = item.get("traits") or {}
        traits = traits_data.get("value", [])
        if traits:
            trait_text = " ".join([f"`{t}`" for t in traits])
            traits_field = {
                "name": "**Traits**",
                "value": trait_text,
                "inline": False
            }
            embed["fields"].append(traits_field)
        
        # Footer
        source_book = item.get('source', 'N/A')
        embed["footer"] = {"text": f"Source: {source_book} | Archives of Nethys"}
        sanitized_name = re.sub(r'[^a-zA-Z0-9]', '', item['name'])
        embed["thumbnail"] = {"url": f"https://2e.aonprd.com/Images/Equipment/{sanitized_name}.webp"}
        
        return embed
        
    except aiohttp.ClientResponseError as e:
        logging.error(f"AON API request failed: {e}")
        return {
            "title": "Error: Archives of Nethys API",
            "description": f"The API request to Archives of Nethys failed with status: {e.status}",
            "color": 0xFF0000
        }
    except Exception as e:
        logging.exception("An unexpected error occurred in search_item")
        return {
            "title": "Error",
            "description": f"An unexpected error occurred: `{type(e).__name__}: {e}`",
            "color": 0xFF0000
        }

def clean_html(text):
    """Remove HTML tags and unescape entities"""
    text = text.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    text = re.sub(r'<[^>]+>', '', text)
    text = unescape(text)
    return text.strip()
