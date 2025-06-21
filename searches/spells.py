import aiohttp
import re
from html import unescape

async def search_spell(spell_name):
    """Search for a spell on Archives of Nethys and return Discord embed"""
    
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
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=query) as response:
                data = await response.json()
            
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
                async with session.post(url, json=query) as response:
                    data = await response.json()
        
        hits = data.get("hits", {}).get("hits", [])
        if not hits:
            return {
                "title": "Spell Not Found",
                "description": f"No spell matching '{spell_name}' found.",
                "color": 0xFF0000
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
            "description": description[:300] + "..." if len(description) > 300 else description,
            "fields": []
        }
        
        # Spell Details
        details = {
            "name": "**Spell Details**",
            "value": f"Level: {spell.get('level', 'N/A')}\nCast: {spell.get('cast', 'N/A')}\nRange: {spell.get('range', 'N/A')}",
            "inline": True
        }
        embed["fields"].append(details)
        
        # Traditions
        traditions = spell.get("traditions", [])
        if traditions:
            trad_field = {
                "name": "**Traditions**",
                "value": ", ".join(traditions),
                "inline": True
            }
            embed["fields"].append(trad_field)
        
        # Components
        components = spell.get("components", [])
        if components:
            comp_field = {
                "name": "**Components**",
                "value": ", ".join(components),
                "inline": True
            }
            embed["fields"].append(comp_field)
        
        # Traits
        traits = spell.get("traits", {}).get("value", [])
        if traits:
            trait_text = " ".join([f"`{t}`" for t in traits])
            traits_field = {
                "name": "**Traits**",
                "value": trait_text,
                "inline": False
            }
            embed["fields"].append(traits_field)
        
        # Footer
        embed["footer"] = {"text": f"Source: {spell.get('source', 'Core Rulebook')}"}
        
        return embed
        
    except Exception as e:
        return {
            "title": "Error",
            "description": f"Failed to search spell: {str(e)}",
            "color": 0xFF0000
        }

def clean_html(text):
    """Remove HTML tags and unescape entities"""
    text = text.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    text = re.sub(r'<[^>]+>', '', text)
    text = unescape(text)
    return text.strip()
