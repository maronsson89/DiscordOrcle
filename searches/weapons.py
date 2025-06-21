import aiohttp
import re
from html import unescape
import logging

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
        
        # Parse the weapon data
        weapon = hits[0]["_source"]
        
        # Extract and clean description
        text = weapon.get("text", "")
        description = ""
        if "---" in text:
            parts = text.split("---", 1)
            description = clean_html(parts[1].strip() if len(parts) > 1 else parts[0].strip())
            # Remove redundant critical specialization and favored weapon sentences
            description = re.sub(r'[^.]*critical specialization[^.]*\.', '', description, flags=re.IGNORECASE).strip()
            description = re.sub(r'[^.]*favored weapon[^.]*\.', '', description, flags=re.IGNORECASE).strip()
        
        # Build the embed
        embed = {
            "title": f"**{weapon['name']}**",
            "url": f"https://2e.aonprd.com/Weapons.aspx?ID={weapon.get('aonId', '')}",
            "description": description,
            "fields": []
        }
        
        # Properties field
        properties_field = {
            "name": "**Properties**",
            "value": f"**Price**: {weapon.get('price', 'N/A')}\n**Level**: {weapon.get('level', 0)}\n**Bulk**: {weapon.get('bulk', 'N/A')}",
            "inline": True
        }
        embed["fields"].append(properties_field)
        
        # Combat field
        damage = weapon.get("damage", "N/A")
        hands = weapon.get("hands", "N/A")
        combat_field = {
            "name": "**Combat**",
            "value": f"**Damage**: {damage}\n**Hands**: {hands}",
            "inline": True
        }
        embed["fields"].append(combat_field)
        
        # Classification field
        weapon_type = weapon.get("type", "N/A")
        weapon_group = weapon.get("group", "N/A")
        classification_field = {
            "name": "**Classification**",
            "value": f"**Type**: {weapon_type}\n**Group**: {weapon_group}",
            "inline": True
        }
        embed["fields"].append(classification_field)
        
        # Traits field
        traits_data = weapon.get("traits") or {}
        traits = traits_data.get("value", [])
        trait_text = ""
        
        if traits:
            # Check for Versatile trait
            for trait in traits:
                if trait.startswith("versatile-"):
                    letter = trait.split("-")[1].upper()
                    damage_type_map = {"P": "piercing", "B": "bludgeoning", "S": "slashing"}
                    alt_type = damage_type_map.get(letter, "unknown")
                    
                    base_type = "slashing"
                    if "piercing" in damage.lower(): base_type = "piercing"
                    elif "bludgeoning" in damage.lower(): base_type = "bludgeoning"
                    
                    trait_text += f"**Versatile {letter}** — Can be used to deal **{alt_type}** damage instead of **{base_type}**.\n"
                    break
            
            other_traits = " ".join([f"`{t}`" for t in traits if not t.startswith("versatile-")])
            if other_traits:
                trait_text += other_traits
        
        if trait_text:
            traits_field = {
                "name": "**Traits**",
                "value": trait_text,
                "inline": False
            }
            embed["fields"].append(traits_field)
        
        # Footer & Thumbnail
        embed["footer"] = {"text": f"Source: {weapon.get('source', 'N/A')}"}
        embed["thumbnail"] = {"url": f"https://2e.aonprd.com/Images/Weapons/{weapon.get('name', 'Fallback').replace(' ', '')}.webp"}
        
        return embed
        
    except aiohttp.ClientResponseError as e:
        logging.error(f"AON API request failed: {e}")
        return {
            "title": "Error: Archives of Nethys API",
            "description": f"The API request to Archives of Nethys failed with status: {e.status}",
            "color": 0xFF0000
        }
    except Exception as e:
        logging.exception("An unexpected error occurred in search_weapon")
        return {
            "title": "Error",
            "description": f"An unexpected error occurred: `{type(e).__name__}: {e}`",
            "color": 0xFF0000
        }

def clean_html(text):
    """Remove HTML tags and unescape entities"""
    # Convert <br> to newlines
    text = text.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    # Remove all other HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    # Unescape HTML entities
    text = unescape(text)
    return text.strip()
