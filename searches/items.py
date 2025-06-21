import aiohttp
import re
from html import unescape

async def search_item(item_name):
    """Search for an item on Archives of Nethys and return Discord embed"""
    
    url = "https://elasticsearch.aonprd.com/aon/_search"
    
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
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=query) as response:
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
                    data = await response.json()
        
        hits = data.get("hits", {}).get("hits", [])
        if not hits:
            return {
                "title": "Item Not Found",
                "description": f"No item matching '{item_name}' found.",
                "color": 0xFF0000
            }
        
        item = hits[0]["_source"]
        
        # Extract description
        text = item.get("text", "")
        description = ""
        if "---" in text:
            parts = text.split("---", 1)
            if len(parts) > 1:
                description = clean_html(parts[1].strip())
        
        # Build embed
        embed = {
            "title": f"{item['name']} • 🔗",
            "url": f"https://2e.aonprd.com/Equipment.aspx?ID={item.get('aonId', '')}",
            "description": description[:300] + "..." if len(description) > 300 else description,
            "fields": []
        }
        
        # Properties
        properties = {
            "name": "**Properties**",
            "value": f"Price: {item.get('price', 'N/A')}\nLevel: {item.get('level', 0)}\nBulk: {item.get('bulk', 'N/A')}",
            "inline": True
        }
        embed["fields"].append(properties)
        
        # Usage
        usage = {
            "name": "**Usage**",
            "value": f"Worn: {item.get('usage', 'N/A')}\nHands: {item.get('hands', 'N/A')}",
            "inline": True
        }
        embed["fields"].append(usage)
        
        # Traits
        traits = item.get("traits", {}).get("value", [])
        if traits:
            trait_text = " ".join([f"`{t}`" for t in traits])
            traits_field = {
                "name": "**Traits**",
                "value": trait_text,
                "inline": False
            }
            embed["fields"].append(traits_field)
        
        # Footer
        embed["footer"] = {"text": f"Source: {item.get('source', 'Core Rulebook')}"}
        
        return embed
        
    except Exception as e:
        return {
            "title": "Error",
            "description": f"Failed to search item: {str(e)}",
            "color": 0xFF0000
        }

def clean_html(text):
    """Remove HTML tags and unescape entities"""
    text = text.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    text = re.sub(r'<[^>]+>', '', text)
    text = unescape(text)
    return text.strip()
