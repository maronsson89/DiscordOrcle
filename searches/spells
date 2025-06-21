import requests
import re
from html import unescape

def clean_html(text):
    """Remove HTML tags and unescape entities"""
    text = text.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    text = re.sub(r'<[^>]+>', '', text)
    text = unescape(text)
    return text.strip()

def search_spell(spell_name):
    """Search for a spell on Archives of Nethys and return a Discord embed dictionary"""
    
    url = "https://elasticsearch.aonprd.com/aon/_search"
    
    # Try exact match first
    query = {
        "query": {
            "bool": {
                "must": [
                    {"term": {"category": "spell"}},
                    {"term": {"name.keyword": spell_name.lower()}}
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
                            {"term": {"category": "spell"}},
                            {"match": {"name": spell_name}}
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
                "title": "Spell Not Found",
                "description": f"No spell matching '{spell_name}' found.",
                "color": 0xFF0000 # Red
            }
        
        spell = hits[0]["_source"]
        
        # Extract description
        text = spell.get("text", "")
        description = ""
        if "---" in text:
            parts = text.split("---", 1)
            if len(parts) > 1:
                description = clean_html(parts[1].strip())
        
        # Build embed
        embed = {
            "title": f"{spell['name']} • 🔗",
            "url": f"https://2e.aonprd.com/Spells.aspx?ID={spell.get('aonId', '')}",
            "description": (description[:400] + "...") if len(description) > 400 else description,
            "fields": [],
            "color": 0x5865F2 # Discord Blurple
        }
        
        # Spell Details
        embed["fields"].append({
            "name": "**Spell Details**",
            "value": f"Level: {spell.get('level', 'N/A')}\nCast: {spell.get('cast', 'N/A')}\nRange: {spell.get('range', 'N/A')}",
            "inline": True
        })
        
        # Traditions
        traditions = spell.get("traditions", [])
        if traditions:
            embed["fields"].append({
                "name": "**Traditions**",
                "value": ", ".join(traditions).title(),
                "inline": True
            })
            
        # Components
        components = spell.get("components", [])
        if components:
             embed["fields"].append({
                "name": "**Components**",
                "value": ", ".join(components).title(),
                "inline": True
            })

        # Traits
        traits = spell.get("traits", {}).get("value", [])
        if traits:
            trait_text = " ".join([f"`{t}`" for t in traits])
            embed["fields"].append({
                "name": "**Traits**",
                "value": trait_text,
                "inline": False
            })
            
        # Footer
        embed["footer"] = {"text": f"Source: {spell.get('source', 'N/A')}"}
        
        return embed

    except requests.exceptions.RequestException as e:
        print(f"Network error searching for spell: {e}")
        return {"title": "Network Error", "description": "Could not connect to Archives of Nethys.", "color": 0xFF0000}
    except Exception as e:
        print(f"An unexpected error occurred in search_spell: {e}")
        return {
            "title": "Error",
            "description": f"An unexpected error occurred while searching for the spell.",
            "color": 0xFF0000
        }
