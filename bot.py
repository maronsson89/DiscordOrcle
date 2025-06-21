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
