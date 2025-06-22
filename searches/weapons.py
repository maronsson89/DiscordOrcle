import aiohttp
import re
from html import unescape
import logging
import asyncio
from urllib.parse import quote, quote_plus

async def search_weapon(weapon_name):
    """Search for a weapon on Archives of Nethys and return Discord embed"""

    url = "https://elasticsearch.aonprd.com/aon/_search"
    timeout = aiohttp.ClientTimeout(total=10)

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

            if not data.get("hits", {}).get("hits"):
                query["query"]["bool"]["must"][1] = {"match": {"name": weapon_name}}
                async with session.post(url, json=query) as response:
                    response.raise_for_status()
                    data = await response.json()

        hits = data.get("hits", {}).get("hits", [])
        if not hits:
            return {"title": "Weapon Not Found", "description": f"No weapon matching '{weapon_name}' found.", "color": 0xFFAD00}

        weapon = hits[0]["_source"]
        full_text = clean_html(weapon.get("text", ""))

        # --- NEW PARSING LOGIC BASED ON PROVIDED DATA ---
        description_flavor = ""
        metadata_block = full_text
        if "---" in full_text:
            parts = full_text.split("---", 1)
            metadata_block = parts[0]
            flavor_text_raw = parts[1].strip()
            description_flavor = flavor_text_raw.split("Critical Specialization Effects")[0].strip()

        def extract(pattern, text, default="N/A"):
            match = re.search(pattern, text, re.IGNORECASE)
            return " ".join(match.group(1).strip().split()) if match else default

        price = extract(r"Price\s(.*?)\s*Damage", metadata_block)
        damage = extract(r"Damage\s(.*?)\s*Bulk", metadata_block)
        bulk = extract(r"Bulk\s(.*?)\s*Hands", metadata_block)
        hands = extract(r"Hands\s(.*?)\s*Type", metadata_block)
        weapon_type = extract(r"Type\s(.*?)\s*Category", metadata_block)
        category = extract(r"Category\s(.*?)\s*Group", metadata_block)
        group = extract(r"Group\s(.*)", metadata_block)
        
        source_data = weapon.get('source', 'N/A')
        source = source_data[0] if isinstance(source_data, list) else source_data
        level = weapon.get('level', 0)

        aon_id = weapon.get('aonId')
        link = f"https://2e.aonprd.com/Search.aspx?q={quote_plus(weapon.get('name', ''))}"
        if aon_id:
            link = f"https://2e.aonprd.com/Weapons.aspx?ID={aon_id}"

        # --- Build Final Embed ---
        embed = {
            "title": weapon.get('name', 'Unknown Weapon'),
            "url": link,
            "description": description_flavor,
            "fields": [
                {
                    "name": "Properties",
                    "value": f"**Price**: {price}\n**Level**: {level}\n**Bulk**: {bulk}",
                    "inline": True
                },
                {
                    "name": "Combat",
                    "value": f"**Damage**: {damage}\n**Hands**: {hands}",
                    "inline": True
                },
                {
                    "name": "Classification",
                    "value": f"**Type**: {weapon_type}\n**Category**: {category}\n**Group**: {group}",
                    "inline": True
                }
            ],
            "footer": {"text": f"Source: {source} | Archives of Nethys"}
        }
        return embed

    except Exception as e:
        logging.exception("An error occurred in search_weapon")
        return {"title": "Error", "description": f"An unexpected error occurred: {type(e).__name__}", "color": 0xFF0000}

def clean_html(text):
    text = re.sub(r'<[^>]+>', '', text)
    return unescape(text).strip()
