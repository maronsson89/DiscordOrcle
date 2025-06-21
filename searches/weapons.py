import aiohttp
import re
from html import unescape

async def search_weapon(weapon_name):
    """Search for a weapon on Archives of Nethys and return Discord embed"""
    
    # Elasticsearch query
    url = "https://elasticsearch.aonprd.com/aon/_search"
    
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
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=query) as response:
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
                    data = await response.json()
        
        # Check if we got results
        hits = data.get("hits", {}).get("hits", [])
        if not hits:
            return {
                "title": "Item Not Found",
                "description": f"No weapon matching '{weapon_name}' found.",
                "color": 0xFF0000
            }
        
        # Parse the weapon data
        weapon = hits[0]["_source"]
        
        # Extract and clean description (text after first ---)
        text = weapon.get("text", "")
        description = ""
        if "---" in text:
            parts = text.split("---", 1)
            if len(parts) > 1:
                description = clean_html(parts[1].strip())
                # Remove critical specialization and favored weapon sentences
                description = re.sub(r'[^.]*critical specialization[^.]*\.', '', description, flags=re.IGNORECASE)
                description = re.sub(r'[^.]*favored weapon[^.]*\.', '', description, flags=re.IGNORECASE)
                description = description.strip()
        
        # Build the embed
        embed = {
            "title": f"{weapon['name']} • 🔗",
            "url": f"https://2e.aonprd.com/Weapons.aspx?ID={weapon.get('aonId', '')}",
            "description": description[:200] + "..." if len(description) > 200 else description,
            "fields": []
        }
        
        # Properties field
        properties_field = {
            "name": "**Properties**",
            "value": f"Price: {weapon.get('price', 'N/A')}\nLevel: {weapon.get('level', 0)}\nBulk: {weapon.get('bulk', 'N/A')}",
            "inline": True
        }
        embed["fields"].append(properties_field)
        
        # Combat field
        damage = weapon.get("damage", "N/A")
        hands = weapon.get("hands", "N/A")
        combat_field = {
            "name": "**Combat**",
            "value": f"Damage: {damage}\nHands: {hands}",
            "inline": True
        }
        embed["fields"].append(combat_field)
        
        # Classification field
        weapon_type = weapon.get("type", "N/A")
        weapon_group = weapon.get("group", "N/A")
        classification_field = {
            "name": "**Classification**",
            "value": f"Type: {weapon_type}\nGroup: {weapon_group}",
            "inline": True
        }
        embed["fields"].append(classification_field)
        
        # Traits field
        traits = weapon.get("traits", {}).get("value", [])
        trait_text = ""
        
        # Check for Versatile trait
        for trait in traits:
            if trait.startswith("versatile-"):
                letter = trait.split("-")[1].upper()
                damage_type_map = {"P": "piercing", "B": "bludgeoning", "S": "slashing"}
                alt_type = damage_type_map.get(letter, "unknown")
                
                # Extract base damage type from damage string
                base_type = "slashing"  # default
                if "piercing" in damage.lower():
                    base_type = "piercing"
                elif "bludgeoning" in damage.lower():
                    base_type = "bludgeoning"
                
                trait_text = f"Versatile {letter} — Can be used to deal **{alt_type}** damage instead of its normal **{base_type}** damage. You choose the damage type each time you attack.\n"
                break
        
        # Add other traits as code blocks
        other_traits = [f"`{t}`" for t in traits if not t.startswith("versatile-")]
        if other_traits:
            trait_text += " ".join(other_traits)
        
        if trait_text:
            traits_field = {
                "name": "**Traits**",
                "value": trait_text,
                "inline": False
            }
            embed["fields"].append(traits_field)
        
        # Footer
        source = weapon.get("source", "Core Rulebook")
        embed["footer"] = {"text": f"Source: {source}"}
        
        return embed
        
    except Exception as e:
        return {
            "title": "Error",
            "description": f"Failed to search weapon: {str(e)}",
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
