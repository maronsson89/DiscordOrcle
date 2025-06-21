import requests
import re
from html import unescape

def clean_html(text):
    """Remove HTML tags and unescape entities"""
    text = text.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    text = re.sub(r'<[^>]+>', '', text)
    text = unescape(text)
    return text.strip()

def search_feat(feat_name):
    """Search for a feat on Archives of Nethys and return a Discord embed dictionary"""
    
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
        response = requests.post(url, json=query)
        response.raise_for_status()
        data = response.json()
        
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
            response = requests.post(url, json=query)
            response.raise_for_status()
            data = response.json()
        
        hits = data.get("hits", {}).get("hits", [])
        if not hits:
            return {
                "title": "Feat Not Found",
                "description": f"No feat matching '{feat_name}' found.",
                "color": 0xFF0000 # Red
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
            "description": (description[:400] + "...") if len(description) > 400 else description,
            "fields": [],
            "color": 0x5865F2 # Discord Blurple
        }
        
        # Feat Details
        embed["fields"].append({
            "name": "**Details**",
            "value": f"Level: {feat.get('level', 'N/A')}\nPrerequisites: {feat.get('prerequisites', 'None')}",
            "inline": True
        })
        
        # Actions
        actions = feat.get("actions", "")
        if actions:
            embed["fields"].append({
                "name": "**Actions**",
                "value": actions,
                "inline": True
            })
            
        # Traits
        traits = feat.get("traits", {}).get("value", [])
        if traits:
            trait_text = " ".join([f"`{t}`" for t in traits])
            embed["fields"].append({
                "name": "**Traits**",
                "value": trait_text,
                "inline": False
            })
        
        # Footer
        embed["footer"] = {"text": f"Source: {feat.get('source', 'N/A')}"}
        
        return embed

    except requests.exceptions.RequestException as e:
        print(f"Network error searching for feat: {e}")
        return {"title": "Network Error", "description": "Could not connect to Archives of Nethys.", "color": 0xFF0000}
    except Exception as e:
        print(f"An unexpected error occurred in search_feat: {e}")
        return {
            "title": "Error",
            "description": f"An unexpected error occurred while searching for the feat.",
            "color": 0xFF0000
        }
