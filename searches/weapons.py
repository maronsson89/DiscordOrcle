DiscordOrcle Bot Repository
Here are the complete contents for each file in your repository. You can create the file with the specified name and then copy the code block into it.

File: bot.py
import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
from searches.weapons import search_weapon
from searches.items import search_item
from searches.spells import search_spell
from searches.feats import search_feat

# Load environment variables from .env file
load_dotenv()

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='/', intents=intents)

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

@bot.tree.command(name="weapon", description="Search for a PF2e weapon")
async def weapon_command(interaction: discord.Interaction, weapon_name: str):
    await interaction.response.defer()
    embed_data = search_weapon(weapon_name)
    embed = discord.Embed.from_dict(embed_data)
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="item", description="Search for a PF2e item")
async def item_command(interaction: discord.Interaction, item_name: str):
    await interaction.response.defer()
    embed_data = search_item(item_name)
    embed = discord.Embed.from_dict(embed_data)
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="spell", description="Search for a PF2e spell")
async def spell_command(interaction: discord.Interaction, spell_name: str):
    await interaction.response.defer()
    embed_data = search_spell(spell_name)
    embed = discord.Embed.from_dict(embed_data)
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="feat", description="Search for a PF2e feat")
async def feat_command(interaction: discord.Interaction, feat_name: str):
    await interaction.response.defer()
    embed_data = search_feat(feat_name)
    embed = discord.Embed.from_dict(embed_data)
    await interaction.followup.send(embed=embed)

# Get the token from environment variables
DISCORD_ORCLE_TOKEN = os.getenv('DISCORD_ORCLE_TOKEN')

# Run bot
if DISCORD_ORCLE_TOKEN:
    bot.run(DISCORD_ORCLE_TOKEN)
else:
    print("Error: DISCORD_ORCLE_TOKEN not found in environment variables.")
    print("Please create a .env file and add your bot token.")


File: searches/__init__.py
# This file makes the searches directory a Python package.
# You can leave this file empty.

File: searches/weapons.py
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

File: searches/spells.py
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

File: searches/feats.py
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

File: requirements.txt
discord.py>=2.3.0
requests>=2.31.0
python-dotenv>=1.0.0

File: Procfile
(This is for services like Heroku. For Render, you can specify the start command directly in the dashboard.)

worker: python bot.py

File: .env.example
# Copy this file to .env and fill in your API keys
DISCORD_ORCLE_TOKEN=your_discord_bot_token_here
OPENAI_API_KEY=your_openai_api_key_here

File: README.md
# DiscordOrcle

A simple Discord bot for quickly searching Pathfinder 2e content from the Archives of Nethys. The bot uses slash commands for easy interaction.

## Features

- `/weapon [name]` - Search for a specific weapon.
- `/item [name]` - Search for a specific item or piece of equipment.
- `/spell [name]` - Search for a specific spell.
- `/feat [name]` - Search for a specific feat.

## Setup & Running Locally

1.  **Clone Repository:**
    ```bash
    git clone [https://github.com/your-username/DiscordOrcle.git](https://github.com/your-username/DiscordOrcle.git)
    cd DiscordOrcle
    ```

2.  **Create a Virtual Environment:**
    ```bash
    # For Windows
    python -m venv venv
    .\venv\Scripts\activate

    # For macOS/Linux
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Set Up Environment Variables:**
    -   Copy the `.env.example` file to a new file named `.env`.
    -   Open the `.env` file and add your secret keys for `DISCORD_ORCLE_TOKEN` and `OPENAI_API_KEY`.

5.  **Run the Bot:**
    ```bash
    python bot.py
    ```

## Deployment

This bot is ready for deployment on services like [Render](https://render.com/) or [Heroku](https://www.heroku.com/).

### Deploying on Render

1.  Push your code to a GitHub repository.
2.  Create a new "Background Worker" service on Render and connect it to your GitHub repository.
3.  Set the **Start Command** to `pip install -r requirements.txt && python bot.py`.
4.  Go to the "Environment" tab and add a new secret file. Name it `.env` and paste the contents of your local `.env` file (containing `DISCORD_ORCLE_TOKEN` and `OPENAI_API_KEY`).
5.  Deploy!

## Adding New Search Types

The bot is structured to be easily extendable. To add a new search command (e.g., for ancestries):

1.  Create a new Python file in the `searches/` directory (e.g., `searches/ancestries.py`).
2.  Inside the new file, create a search function (e.g., `search_ancestry`) following the pattern in the other search files. You'll need to find the correct `category` on Archives of Nethys (e.g., "ancestry") and adjust the embed fields accordingly.
3.  In `bot.py`, import your new search function: `from searches.ancestries import search_ancestry`.
4.  Add a new slash command to `bot.py` that calls your new function.

File: .gitignore
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg
MANIFEST

# Virtual Environments
env/
venv/
ENV/
.venv/

# Environment variables
.env
.env.*
!.env.example

# IDE configuration
.vscode/
.idea/
*.swp
*.swo

# OS-generated files
.DS_Store
.DS_Store?
._*
.Spotlight-V100
.Trashes
ehthumbs.db
Thumbs.db

# Log files
*.log
logs/
