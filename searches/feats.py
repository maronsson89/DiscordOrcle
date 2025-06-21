import aiohttp
import re
from html import unescape

async def search_feat(feat_name):
    """Search for a feat on Archives of Nethys and return Discord embed"""
    
    url = "https://elasticsearch.aonprd.com/aon/_search"
    
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
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=query) as response:
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
                    data = await response.json()
        
        hits = data.get("hits", {}).get("hits", [])
        if not hits:
            return {
                "title": "Feat Not Found",
                "description": f"No feat matching '{feat_name}' found.",
                "color": 0xFF0000
            }
        
        feat = hits[0]["_source"]
        
        # Extract description
        text = feat.get("text", "")
        description = ""
        if "---" in text:
            parts = text.split("---", 1)
            if len(parts) > 1:
                description = clean_html(parts[1].strip())
        
        # Build embed
        embed = {
            "title": f"{feat['name']} • 🔗",
            "url": f"https://2e.aonprd.com/Feats.aspx?ID={feat.get('aonId', '')}",
            "description": description[:300] + "..." if len(description) > 300 else description,
            "fields": []
        }
        
        # Feat Details
        details = {
            "name": "**Details**",
            "value": f"Level: {feat.get('level', 'N/A')}\nPrerequisites: {feat.get('prerequisites', 'None')}",
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
        traits = feat.get("traits", {}).get("value", [])
        if traits:
            trait_text = " ".join([f"`{t}`" for t in traits])
            traits_field = {
                "name": "**Traits**",
                "value": trait_text,
                "inline": False
            }
            embed["fields"].append(traits_field)
        
        # Footer
        embed["footer"] = {"text": f"Source: {feat.get('source', 'Core Rulebook')}"}
        
        return embed
        
    except Exception as e:
        return {
            "title": "Error",
            "description": f"Failed to search feat: {str(e)}",
            "color": 0xFF0000
        }

def clean_html(text):
    """Remove HTML tags and unescape entities"""
    text = text.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    text = re.sub(r'<[^>]+>', '', text)
    text = unescape(text)
    return text.strip()
