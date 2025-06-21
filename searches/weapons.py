import requests
import re
from html import unescape

def clean_html(text):
    """Remove HTML tags and unescape entities"""
    # Convert <br> to newlines
    text = text.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    # Remove all other HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    # Unescape HTML entities
    text = unescape(text)
    return text.strip()

def search_weapon(weapon_name):
    """Search for a weapon on Archives of Nethys and return a Discord embed dictionary"""
    
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
        response = requests.post(url, json=query)
        response.raise_for_status()
        data = response.json()
        
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
            response = requests.post(url, json=query)
            response.raise_for_status()
            data = response.json()
        
        # Check if we got results
        hits = data.get("hits", {}).get("hits", [])
        if not hits:
            return {
                "title": "Weapon Not Found",
                "description": f"No weapon matching '{weapon_name}' found.",
                "color": 0xFF0000 # Red
            }
        
        # Parse the weapon data
        weapon = hits[0]["_source"]
        
        # Extract and clean description
        text = weapon.get("text", "")
        description = ""
        if "---" in text:
            parts = text.split("---", 1)
            if len(parts) > 1:
                description = clean_html(parts[1].strip())
                # Remove Critical Specialization and Favored Weapon sentences
                description = re.sub(r'[^.]*critical specialization[^.]*\.', '', description, flags=re.IGNORECASE)
                description = re.sub(r'[^.]*favored weapon[^.]*\.', '', description, flags=re.IGNORECASE)
                description = description.strip()
        
        # Build the embed
        embed = {
            "title": f"{weapon['name']} • 🔗",
            "url": f"https://2e.aonprd.com/Weapons.aspx?ID={weapon.get('aonId', '')}",
            "description": (description[:400] + "...") if len(description) > 400 else description,
            "fields": [],
            "color": 0x5865F2 # Discord Blurple
        }
        
        # Properties field
        embed["fields"].append({
            "name": "**Properties**",
            "value": f"Price: {weapon.get('price', 'N/A')}\nLevel: {weapon.get('level', 0)}\nBulk: {weapon.get('bulk', 'N/A')}",
            "inline": True
        })
        
        # Combat field
        damage = weapon.get("damage", "N/A")
        hands = weapon.get("hands", "N/A")
        embed["fields"].append({
            "name": "**Combat**",
            "value": f"Damage: {damage}\nHands: {hands}",
            "inline": True
        })
        
        # Classification field
        embed["fields"].append({
            "name": "**Classification**",
            "value": f"Type: {weapon.get('type', 'N/A')}\nGroup: {weapon.get('group', 'N/A')}",
            "inline": True
        })
        
        # Traits field
        traits = weapon.get("traits", {}).get("value", [])
        trait_text = ""
        
        # Handle Versatile trait specially
        for trait in traits:
            if trait.startswith("versatile-"):
                letter = trait.split("-")[1].upper()
                damage_type_map = {"P": "piercing", "B": "bludgeoning", "S": "slashing"}
                alt_type = damage_type_map.get(letter, "unknown")
                
                # Determine base damage type for context
                base_type = "slashing" # default
                if "piercing" in str(damage).lower():
                    base_type = "piercing"
                elif "bludgeoning" in str(damage).lower():
                    base_type = "bludgeoning"
                
                trait_text += f"**Versatile {letter}**: Can be used to deal **{alt_type}** damage instead of its normal **{base_type}** damage.\n"
                break # Assume only one versatile trait
        
        other_traits = [f"`{t}`" for t in traits if not t.startswith("versatile-")]
        if other_traits:
            trait_text += " ".join(other_traits)
        
        if trait_text:
            embed["fields"].append({
                "name": "**Traits**",
                "value": trait_text,
                "inline": False
            })
            
        # Footer
        source = weapon.get("source", "N/A")
        embed["footer"] = {"text": f"Source: {source}"}
        
        return embed
        
    except requests.exceptions.RequestException as e:
        print(f"Network error searching for weapon: {e}")
        return {"title": "Network Error", "description": "Could not connect to Archives of Nethys.", "color": 0xFF0000}
    except Exception as e:
        print(f"An unexpected error occurred in search_weapon: {e}")
        return {
            "title": "Error",
            "description": f"An unexpected error occurred while searching for the weapon.",
            "color": 0xFF0000
        }

File: searches/items.py
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
