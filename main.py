import discord
from discord import app_commands
from discord.ext import commands
import aiohttp
import json
import re
import os
from typing import Dict, List, Optional, Tuple
from openai import AsyncOpenAI

# Bot configuration
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Initialize OpenAI client
openai_client = AsyncOpenAI(api_key=os.environ.get('OPENAI_API_KEY'))

class AoNFormatter:
    """Handles formatting of Archives of Nethys API data into Discord embeds using ChatGPT"""
    
    SYSTEM_PROMPT = """You are a Discord bot formatter for Archives of Nethys weapon data. Transform raw JSON data into formatted text following these EXACT rules:

1. MAIN DESCRIPTION: Extract flavor text after "---" separator. Remove sentences containing "critical specialization" or "favored weapon".

2. TRAITS: 
   - For "Versatile" trait: Write "Can be used to deal [alternate type] damage instead of its normal [base type] damage. You choose the damage type each time you attack."
   - Other traits: Just return the trait name

3. STATISTICS (return as JSON object with three categories):
   - Properties: Price, Level, Bulk
   - Combat: Damage, Hands  
   - Classification: Type, Group, Category (use Title Case)

4. CRITICAL SPECIALIZATION: 
   - Format: "[Group Name]: [Effect Text]"
   - Use "off-guard" terminology instead of "flat-footed"
   - Include standard second line: "Certain feats, class features, weapon runes, and other effects can grant you additional benefits."

5. CONTEXTUAL FIELDS: Find "Favored Weapon of" and "Specific Magic Longswords" in text. Extract content after these labels until the next keyword (Price, Damage, Source, ---, etc).

Return a JSON object with these keys: description, traits, properties, combat, classification, critical_spec, favored_weapon (if found), specific_magic (if found)."""

    @staticmethod
    async def process_with_gpt(data: Dict) -> Dict:
        """Process weapon data using ChatGPT mini"""
        try:
            response = await openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": AoNFormatter.SYSTEM_PROMPT},
                    {"role": "user", "content": f"Process this weapon data:\n{json.dumps(data)}"}
                ],
                temperature=0.3,
                max_tokens=1000
            )
            
            # Parse the GPT response
            result = response.choices[0].message.content
            return json.loads(result)
        except Exception as e:
            print(f"GPT processing error: {e}")
            # Fallback to manual processing
            return AoNFormatter.manual_process(data)
    
    @staticmethod
    def manual_process(data: Dict) -> Dict:
        """Fallback manual processing if GPT fails"""
        text = data.get('text', '')
        
        # Extract main description
        description = "No description available."
        if '---' in text:
            parts = text.split('---')
            if len(parts) > 1:
                desc_text = parts[1].strip()
                sentences = desc_text.split('.')
                filtered = [s.strip() for s in sentences 
                           if s.strip() and not any(phrase in s.lower() for phrase in 
                                                   ['critical specialization', 'favored weapon'])]
                if filtered:
                    description = '. '.join(filtered) + '.'
        
        # Format traits
        traits = []
        for trait in data.get('trait', []):
            if isinstance(trait, dict):
                name = trait.get('name', '')
                value = trait.get('value', '')
                if 'versatile' in name.lower():
                    base_type = 'slashing'  # Default, should be extracted from damage
                    alt_type = value.lower() if value else 'piercing'
                    traits.append(f"**Versatile ({value})**: Can be used to deal {alt_type} damage instead of its normal {base_type} damage. You choose the damage type each time you attack.")
                else:
                    traits.append(name)
            else:
                traits.append(str(trait))
        
        # Extract statistics
        properties = {
            "Price": data.get('price', 'N/A'),
            "Level": str(data.get('level', 'N/A')),
            "Bulk": data.get('bulk', 'N/A')
        }
        
        combat = {
            "Damage": data.get('damage', 'N/A'),
            "Hands": str(data.get('hands', 'N/A'))
        }
        
        classification = {
            "Type": (data.get('weapon_type', 'N/A')).title(),
            "Group": (data.get('group', 'N/A')).title(),
            "Category": (data.get('category', 'N/A')).title()
        }
        
        # Critical specialization
        group = data.get('group', 'Unknown')
        crit_effects = {
            'sword': 'The target is made off-guard until the start of your next turn',
            'axe': 'Choose one creature adjacent to the initial target and within reach. If its AC is lower, you deal damage to it equal to the number of damage dice',
            'hammer': 'The target is knocked prone',
            'spear': 'The weapon pierces the target, weakening its attacks. The target is clumsy 1',
            'knife': 'The target takes persistent bleed damage equal to the weapon\'s damage dice',
            'flail': 'The target is knocked prone',
            'polearm': 'The target is moved 5 feet in a direction of your choice',
            'shield': 'You knock the target back 5 feet',
            'bow': 'If the target is within 30 feet, it\'s immobilized',
            'brawling': 'The target must succeed at a Fortitude save or be slowed 1',
            'club': 'You knock the target up to 10 feet away',
            'dart': 'The target takes persistent bleed damage equal to the weapon\'s damage dice',
            'firearm': 'The target is stunned 1',
            'pick': 'The weapon pierces through the target\'s armor. The target takes 2 additional damage per weapon damage die',
            'sling': 'The target is stunned 1'
        }
        effect = crit_effects.get(group.lower(), 'Special effect based on weapon group')
        critical_spec = f"**{group.title()}**: {effect}\n\nCertain feats, class features, weapon runes, and other effects can grant you additional benefits."
        
        # Extract contextual fields
        favored_weapon = None
        specific_magic = None
        
        if 'Favored Weapon of' in text:
            match = re.search(r'Favored Weapon of\s*([^.]+?)(?=\s*(?:Price|Damage|Source|---|$))', text)
            if match:
                favored_weapon = match.group(1).strip()
        
        if 'Specific Magic' in text:
            match = re.search(r'Specific Magic (?:Longswords|Weapons)\s*([^.]+?)(?=\s*(?:Price|Damage|Source|---|$))', text)
            if match:
                specific_magic = match.group(1).strip()
        
        return {
            "description": description,
            "traits": traits,
            "properties": properties,
            "combat": combat,
            "classification": classification,
            "critical_spec": critical_spec,
            "favored_weapon": favored_weapon,
            "specific_magic": specific_magic
        }
    
    @staticmethod
    async def create_embed(data: Dict) -> discord.Embed:
        """Create a Discord embed from AoN weapon data using GPT processing"""
        # Process data with GPT
        processed = await AoNFormatter.process_with_gpt(data)
        
        # Create base embed
        name = data.get('name', 'Unknown Weapon')
        embed = discord.Embed(
            title=name,
            color=discord.Color.blue()
        )
        
        # Add main description
        embed.description = processed.get('description', 'No description available.')
        
        # Add traits field
        traits = processed.get('traits', [])
        traits_text = '\n'.join([f"`{t}`" if not t.startswith('**') else t for t in traits])
        embed.add_field(name="Traits", value=traits_text or "None", inline=False)
        
        # Add statistics fields (3 columns)
        props = processed.get('properties', {})
        combat = processed.get('combat', {})
        classification = processed.get('classification', {})
        
        props_text = '\n'.join([f"**{k}**: {v}" for k, v in props.items()])
        combat_text = '\n'.join([f"**{k}**: {v}" for k, v in combat.items()])
        class_text = '\n'.join([f"**{k}**: {v}" for k, v in classification.items()])
        
        embed.add_field(name="Properties", value=props_text, inline=True)
        embed.add_field(name="Combat", value=combat_text, inline=True)
        embed.add_field(name="Classification", value=class_text, inline=True)
        
        # Add critical specialization field
        crit_spec = processed.get('critical_spec', 'No critical specialization available.')
        embed.add_field(name="Critical Specialization Effects", value=crit_spec, inline=False)
        
        # Add contextual fields if present
        if processed.get('favored_weapon'):
            embed.add_field(name="Favored Weapon", value=processed['favored_weapon'], inline=False)
        
        if processed.get('specific_magic'):
            embed.add_field(name="Specific Magic", value=processed['specific_magic'], inline=False)
        
        # Add source if available
        source = data.get('source', {})
        if isinstance(source, dict) and source.get('value'):
            embed.set_footer(text=f"Source: {source['value']}")
        
        return embed

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')
    print(f'OpenAI API Key: {"Set" if os.environ.get("OPENAI_API_KEY") else "Not Set"}')
    
    try:
        # Sync commands globally (or use guild-specific for faster testing)
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

@bot.tree.command(name="weapon", description="Fetch weapon data from Archives of Nethys")
@app_commands.describe(weapon_name="Name of the weapon to look up")
async def fetch_weapon(interaction: discord.Interaction, weapon_name: str):
    """Fetch weapon data from AoN API and display it"""
    # Defer the response since API calls might take time
    await interaction.response.defer()
    
    # Note: Replace with actual AoN API endpoint
    api_url = f"https://api.archivesofnethys.com/v1/weapon/{weapon_name.lower().replace(' ', '-')}"
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(api_url) as response:
                if response.status == 200:
                    data = await response.json()
                    embed = await AoNFormatter.create_embed(data)
                    await interaction.followup.send(embed=embed)
                else:
                    await interaction.followup.send(f"Could not find weapon '{weapon_name}'")
        except Exception as e:
            await interaction.followup.send(f"Error fetching weapon data: {str(e)}")

@bot.tree.command(name="parseweapon", description="Parse raw JSON weapon data")
@app_commands.describe(json_data="Raw JSON data from Archives of Nethys API")
async def parse_weapon_json(interaction: discord.Interaction, json_data: str):
    """Parse raw JSON weapon data and display it using ChatGPT"""
    # Defer the response since GPT processing might take time
    await interaction.response.defer()
    
    try:
        # Clean up the JSON data (remove code blocks if present)
        json_data = json_data.strip()
        if json_data.startswith('```') and json_data.endswith('```'):
            json_data = json_data[3:-3]
        if json_data.startswith('json'):
            json_data = json_data[4:]
        
        data = json.loads(json_data.strip())
        embed = await AoNFormatter.create_embed(data)
        await interaction.followup.send(embed=embed)
    except json.JSONDecodeError:
        await interaction.followup.send("Invalid JSON data. Please provide valid JSON.")
    except Exception as e:
        await interaction.followup.send(f"Error processing weapon data: {str(e)}")

@bot.tree.command(name="testweapon", description="Test the formatter with sample weapon data")
async def test_weapon(interaction: discord.Interaction):
    """Test command with sample weapon data"""
    # Defer the response
    await interaction.response.defer()
    
    sample_data = {
        "name": "Longsword",
        "level": 0,
        "price": "15 gp",
        "bulk": "1",
        "damage": "1d8 slashing",
        "hands": "1",
        "weapon_type": "martial",
        "group": "sword",
        "category": "simple",
        "trait": [
            {"name": "Versatile", "value": "P"},
            {"name": "Reach", "value": ""}
        ],
        "text": "Longswords can be one-edged or two-edged swords. Their blades are heavy and they're between 3 and 4 feet in length. --- Whether blade or bludgeon, a longsword is a classic weapon of melee combat. The longsword is characterized by its long grip and straight, double-edged blade. It's a favored weapon among knights and nobility. Critical specialization effects are nice. Favored Weapon of Iomedae and Ragathiel. Price varies by material.",
        "source": {"value": "Core Rulebook"}
    }
    
    embed = await AoNFormatter.create_embed(sample_data)
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="gpttest", description="Test if GPT connection is working")
async def test_gpt_connection(interaction: discord.Interaction):
    """Test if GPT connection is working"""
    await interaction.response.defer()
    
    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "Say 'GPT connection successful!'"}],
            max_tokens=50
        )
        await interaction.followup.send(f"✅ {response.choices[0].message.content}")
    except Exception as e:
        await interaction.followup.send(f"❌ GPT connection failed: {str(e)}")

@bot.tree.command(name="synccommands", description="Manually sync slash commands (Admin only)")
@app_commands.default_permissions(administrator=True)
async def sync_commands(interaction: discord.Interaction):
    """Manually sync slash commands"""
    await interaction.response.defer()
    
    try:
        synced = await bot.tree.sync()
        await interaction.followup.send(f"✅ Successfully synced {len(synced)} command(s)")
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to sync commands: {str(e)}")

# Error handler for slash commands
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CommandOnCooldown):
        await interaction.response.send_message(f"Command is on cooldown. Try again in {error.retry_after:.2f} seconds.", ephemeral=True)
    else:
        await interaction.response.send_message("An error occurred while processing the command.", ephemeral=True)
        print(f"Error: {error}")

# Run the bot
if __name__ == "__main__":
    # Get tokens from environment variables
    discord_token = os.environ.get('DISCORD_BOT_TOKEN')
    openai_key = os.environ.get('OPENAI_API_KEY')
    
    if not discord_token:
        raise ValueError("DISCORD_BOT_TOKEN environment variable not set")
    if not openai_key:
        print("WARNING: OPENAI_API_KEY not set. GPT features will use fallback processing.")
    
    bot.run(discord_token)
