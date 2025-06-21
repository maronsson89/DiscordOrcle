import discord
from discord import app_commands
import os
from searches.weapons import search_weapon
from searches.items import search_item
from searches.spells import search_spell
from searches.feats import search_feat

# Bot setup
intents = discord.Intents.default()
intents.message_content = True

class MyBot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        
    async def on_ready(self):
        print(f'{self.user} has connected to Discord!')
        try:
            synced = await self.tree.sync()
            print(f"Synced {len(synced)} command(s)")
        except Exception as e:
            print(f"Failed to sync commands: {e}")

bot = MyBot()
tree = bot.tree

@tree.command(name="weapon", description="Search for a PF2e weapon")
async def weapon_command(interaction: discord.Interaction, weapon_name: str):
    await interaction.response.defer()
    embed_data = await search_weapon(weapon_name)
    embed = discord.Embed.from_dict(embed_data)
    await interaction.followup.send(embed=embed)

@tree.command(name="item", description="Search for a PF2e item")
async def item_command(interaction: discord.Interaction, item_name: str):
    await interaction.response.defer()
    embed_data = await search_item(item_name)
    embed = discord.Embed.from_dict(embed_data)
    await interaction.followup.send(embed=embed)

@tree.command(name="spell", description="Search for a PF2e spell")
async def spell_command(interaction: discord.Interaction, spell_name: str):
    await interaction.response.defer()
    embed_data = await search_spell(spell_name)
    embed = discord.Embed.from_dict(embed_data)
    await interaction.followup.send(embed=embed)

@tree.command(name="feat", description="Search for a PF2e feat")
async def feat_command(interaction: discord.Interaction, feat_name: str):
    await interaction.response.defer()
    embed_data = await search_feat(feat_name)
    embed = discord.Embed.from_dict(embed_data)
    await interaction.followup.send(embed=embed)

# Run bot
bot.run(os.getenv('DISCORDORACLE'))
