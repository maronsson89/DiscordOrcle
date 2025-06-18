# main.py
# A Discord bot that searches the Archives of Nethys for Pathfinder 2e items.
# This version is simplified for professional hosting (e.g., Render, Heroku).

import discord
import os
import requests
from bs4 import BeautifulSoup
import urllib.parse

# --- CONFIGURATION ---
# The bot will read its token from a secure environment variable.
try:
    # On Render, you will set an environment variable named 'DiscordOracle'.
    TOKEN = os.getenv('DiscordOracle')
    if TOKEN is None:
        print("Error: DiscordOracle environment variable not set.")
        print("Please set this in your hosting platform's dashboard.")
        exit()
except Exception as e:
    print(f"Error reading environment variable: {e}")
    exit()

# The command prefix the bot will listen for.
COMMAND_PREFIX = "!aon"

# Base URL for Archives of Nethys searches.
AON_BASE_URL = "https://2e.aonprd.com/"

# --- BOT SETUP ---

# To read message content, we need to enable the specific intent.
intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)

def search_archives_of_nethys(query: str):
    """
    Searches Archives of Nethys for a given query, scrapes the first result,
    and returns its details.

    Args:
        query (str): The search term (e.g., "Healing Potion").

    Returns:
        dict: A dictionary containing the item's 'name', 'url', and 'description'.
              Returns None if the item is not found or an error occurs.
    """
    print(f"Searching for: {query}")
    try:
        # 1. Perform the initial search to find the item's page URL.
        # We URL-encode the query to handle spaces and special characters.
        search_query = urllib.parse.quote_plus(query)
        search_url = f"{AON_BASE_URL}Search.aspx?q={search_query}"
        
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36'}

        search_response = requests.get(search_url, headers=headers, timeout=10)
        search_response.raise_for_status() # Will raise an exception for 4XX/5XX status codes

        # 2. Parse the search results page to find the first valid link.
        soup = BeautifulSoup(search_response.content, 'html.parser')
        
        result_link_element = soup.select_one('h1.title + ul.compact li a[href^="Equipment.aspx"]')

        if not result_link_element:
            print("No matching equipment link found on search results page.")
            return None

        item_page_url = AON_BASE_URL + result_link_element['href']
        
        # 3. Scrape the actual item page.
        item_response = requests.get(item_page_url, headers=headers, timeout=10)
        item_response.raise_for_status()
        
        item_soup = BeautifulSoup(item_response.content, 'html.parser')

        # 4. Extract the relevant information from the item page.
        item_name = item_soup.find('h1', class_='title').get_text(strip=True)
        main_content = item_soup.find('span', id='ctl00_MainContent_DetailedOutput')
        
        if not main_content:
            print("Could not find the main content block on the item page.")
            return None
        
        for br in main_content.find_all("br"):
            br.replace_with("\n")
        
        description = main_content.get_text(separator=' ', strip=True)

        if len(description) > 4000:
            description = description[:4000] + "\n\n... (description truncated)"
            
        return {
            'name': item_name,
            'url': item_page_url,
            'description': description
        }

    except requests.exceptions.RequestException as e:
        print(f"An HTTP error occurred: {e}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred during scraping: {e}")
        return None

# --- DISCORD EVENTS ---

@client.event
async def on_ready():
    """Called when the bot successfully logs in."""
    print(f'Bot is ready and logged in as {client.user}')
    print('-----------------------------------------')

@client.event
async def on_message(message):
    """Called every time a message is sent in a channel the bot can see."""
    if message.author == client.user:
        return

    if message.content.startswith(COMMAND_PREFIX + " "):
        query = message.content[len(COMMAND_PREFIX)+1:].strip()

        if not query:
            await message.channel.send("Please provide an item to search for. Usage: `!aon <item name>`")
            return

        processing_message = await message.channel.send(f"🔍 Searching for `{query}` on the Archives...")
        item_data = search_archives_of_nethys(query)
        await processing_message.delete()

        if item_data:
            embed = discord.Embed(
                title=item_data['name'],
                url=item_data['url'],
                description=item_data['description'],
                color=discord.Color.dark_red()
            )
            embed.set_footer(text="Data sourced from Archives of Nethys (2e.aonprd.com)")
            await message.channel.send(embed=embed)
        else:
            await message.channel.send(f"Sorry, I couldn't find an item matching `{query}`. Please check your spelling or try a different term.")

# --- RUN THE BOT ---
if __name__ == "__main__":
    client.run(TOKEN)
