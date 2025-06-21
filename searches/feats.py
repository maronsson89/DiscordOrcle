import aiohttp
import re
from html import unescape
import logging

async def search_feat(feat_name):
    """Search for a feat on Archives of Nethys and return Discord embed"""
    
    url = "https://elasticsearch.aonprd.com/aon/_search"
    timeout = aiohttp.ClientTimeout(total=10)
    
    # Try exact match first
    query = {
        "query": {
            "bool": {
                "must": [
                    {"term": {"category": "feat"}},
                    {"term": {"name.keyword": feat_name.lower()}}
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
                                {"term": {"category": "feat"}},
                                {"match": {"name": feat_name}}
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
                "title": "Feat Not Found",
                "description": f"No feat matching '{feat_name}' found on the Archives of Nethys.",
                "color": 0xFFAD00 # Amber
            }
        
        feat = hits[0]["_source"]
        
        # Extract description
        text = feat.get("text", "")
        description = ""
        if "---" in text:
            description = clean_html(text.split("---", 1)[0].strip())
        else:
            description = clean_html(text)
        
        # Build embed
        embed = {
            "title": f"**{feat['name']}**",
            "url": f"https://2e.aonprd.com/Feats.aspx?ID={feat.get('aonId', '')}",
            "description": description,
            "fields": []
        }
        
        # Feat Details
        details = {
            "name": "**Details**",
            "value": f"**Level**: {feat.get('level', 'N/A')}\n**Prerequisites**: {feat.get('prerequisites', 'None')}",
            "inline": True
        }
        embed["fields"].append(details)
        
        # Actions
        actions = feat.get("actions", "")
        if actions:
            action_field = {
                "name": "**Actions**",
                "value": actions,
                "inline": True
            }
            embed["fields"].append(action_field)
        
        # Traits
        traits_data = feat.get("traits") or {}
        traits = traits_data.get("value", [])
        if traits:
            trait_text = " ".join([f"`{t}`" for t in traits])
            traits_field = {
                "name": "**Traits**",
                "value": trait_text,
                "inline": False
            }
            embed["fields"].append(traits_field)
        
        # Footer & Thumbnail
        source_book = feat.get('source', 'N/A')
        embed["footer"] = {"text": f"Source: {source_book} | Archives of Nethys"}
        embed["thumbnail"] = {"url": "https://2e.aonprd.com/Images/Icons/Feat.png"}
        
        return embed
        
    except aiohttp.ClientResponseError as e:
        logging.error(f"AON API request failed: {e}")
        return {
            "title": "Error: Archives of Nethys API",
            "description": f"The API request to Archives of Nethys failed with status: {e.status}",
            "color": 0xFF0000
        }
    except Exception as e:
        logging.exception("An unexpected error occurred in search_feat")
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
