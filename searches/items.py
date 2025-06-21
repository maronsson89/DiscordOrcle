import requests
import re
from html import unescape

def clean_html(text):
    """Remove HTML tags and unescape entities"""
    text = text.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    text = re.sub(r'<[^>]+>', '', text)
    text = unescape(text)
    return text.strip()

def search_item(item_name):
    """Search for an item on Archives of Nethys and return a Discord embed dictionary"""
    
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
        response = requests.post(url, json=query)
        response.raise_for_status()
        data = response.json()
        
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
            response = requests.post(url, json=query)
            response.raise_for_status()
            data = response.json()
        
        hits = data.get("hits", {}).get("hits", [])
        if not hits:
            return {
                "title": "Item Not Found",
                "description": f"No item matching '{item_name}' found.",
                "color": 0xFF0000 # Red
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
            "description": (description[:400] + "...") if len(description) > 400 else description,
            "fields": [],
            "color": 0x5865F2 # Discord Blurple
        }
        
        # Properties
        embed["fields"].append({
            "name": "**Properties**",
            "value": f"Price: {item.get('price', 'N/A')}\nLevel: {item.get('level', 0)}\nBulk: {item.get('bulk', 'N/A')}",
            "inline": True
        })
        
        # Usage
        embed["fields"].append({
            "name": "**Usage**",
            "value": f"Worn: {item.get('usage', 'N/A')}\nHands: {item.get('hands', 'N/A')}",
            "inline": True
        })
        
        # Traits
        traits = item.get("traits", {}).get("value", [])
        if traits:
            trait_text = " ".join([f"`{t}`" for t in traits])
            embed["fields"].append({
                "name": "**Traits**",
                "value": trait_text,
                "inline": False
            })
            
        # Footer
        embed["footer"] = {"text": f"Source: {item.get('source', 'N/A')}"}
        
        return embed
        
    except requests.exceptions.RequestException as e:
        print(f"Network error searching for item: {e}")
        return {"title": "Network Error", "description": "Could not connect to Archives of Nethys.", "color": 0xFF0000}
    except Exception as e:
        print(f"An unexpected error occurred in search_item: {e}")
        return {
            "title": "Error",
            "description": f"An unexpected error occurred while searching for the item.",
            "color": 0xFF0000
        }
