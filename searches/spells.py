import aiohttp
import re
from html import unescape
import logging
from urllib.parse import quote

async def search_spell(spell_name):
    """Search for a spell on Archives of Nethys and return Discord embed"""
    
    url = "https://elasticsearch.aonprd.com/aon/_search"
    timeout = aiohttp.ClientTimeout(total=10)
    
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
                                {"term": {"category": "spell"}},
                                {"match": {"name": spell_name}}
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
                "title": "Spell Not Found",
                "description": f"No spell matching '{spell_name}' found on the Archives of Nethys.",
                "color": 0xFFAD00 # Amber
            }
        
        spell = hits[0]["_source"]
        
        # Extract description
        text = spell.get("text", "")
        description = ""
        if "---" in text:
            description = clean_html(text.split("---", 1)[0].strip())
        else:
            description = clean_html(text)
        
        # Add link to description if available
        aon_id = spell.get('aonId')
        if aon_id:
            description += f"\n\n[View on Archives of Nethys](https://2e.aonprd.com/Spells.aspx?ID={aon_id})"
        
        # Build embed
        embed = {
            "title": f"**{spell['name']}**",
            "url": f"https://2e.aonprd.com/Spells.aspx?ID={spell.get('aonId', '')}",
            "description": description,
            "fields": []
        }
        
        # Spell Details
        details = {
            "name": "**Spell Details**",
            "value": f"**Level**: {spell.get('level', 'N/A')}\n**Cast**: {spell.get('cast', 'N/A')}\n**Range**: {spell.get('range', 'N/A')}",
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
        traits_data = spell.get("traits") or {}
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
        source_book = spell.get('source', 'N/A')
        embed["footer"] = {"text": f"Source: {source_book} | Archives of Nethys"}
        embed["thumbnail"] = {"url": f"https://2e.aonprd.com/Images/Spells/{quote(spell['name'])}.webp"}
        
        return embed
        
    except aiohttp.ClientResponseError as e:
        logging.error(f"AON API request failed: {e}")
        return {
            "title": "Error: Archives of Nethys API",
            "description": f"The API request to Archives of Nethys failed with status: {e.status}",
            "color": 0xFF0000
        }
    except Exception as e:
        logging.exception("An unexpected error occurred in search_spell")
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
