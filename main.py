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
        print("[ERROR] DiscordOracle environment variable not set.")
        print("Please set this in your hosting platform's dashboard.")
        exit()
except Exception as e:
    print(f"[ERROR] Error reading environment variable: {e}")
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
    print(f"[DEBUG] Starting search for: {query}")
    try:
        # 1. Perform the initial search to find the item's page URL.
        # We URL-encode the query to handle spaces and special characters.
        search_query = urllib.parse.quote_plus(query)
        search_url = f"{AON_BASE_URL}Search.aspx?q={search_query}"
        print(f"[DEBUG] Search URL: {search_url}")

        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36'}

        search_response = requests.get(search_url, headers=headers, timeout=10)
        search_response.raise_for_status() # Will raise an exception for 4XX/5XX status codes
        print(f"[DEBUG] Search response status: {search_response.status_code}")

        # 2. Parse the search results page to find the first valid link.
        soup = BeautifulSoup(search_response.content, 'html.parser')
        
        # This selector looks for an <a> tag that is a child of an <li>
        # which is a child of a <ul class="compact"> that is a sibling of an <h1 class="title">
        # and where the href attribute starts with "Equipment.aspx"
        result_link_element = soup.select_one('h1.title + ul.compact li a[href^="Equipment.aspx"]')
        print(f"[DEBUG] result_link_element found: {result_link_element is not None}")

        if not result_link_element:
            print("[DEBUG] No matching equipment link found on search results page with current selector.")
            # Optionally uncomment to print a snippet of the HTML if the link element is not found
            # print(f"[DEBUG] Search results HTML snippet (first 1000 chars): {soup.prettify()[:1000]}") 
            return None

        item_page_url = AON_BASE_URL + result_link_element['href']
        print(f"[DEBUG] Item page URL: {item_page_url}")
        
        # 3. Scrape the actual item page.
        item_response = requests.get(item_page_url, headers=headers, timeout=10)
        item_response.raise_for_status()
        print(f"[DEBUG] Item page response status: {item_response.status_code}")
        
        item_soup = BeautifulSoup(item_response.content, 'html.parser')

        # 4. Extract the relevant information from the item page.
        item_name_element = item_soup.find('h1', class_='title') 
        if not item_name_element:
            print("[DEBUG] Could not find item name element (h1 with class 'title') on the item page.")
            return None
        item_name = item_name_element.get_text(strip=True)
        print(f"[DEBUG] Item Name: {item_name}")

        main_content = item_soup.find('span', id='ctl00_MainContent_DetailedOutput')
        print(f"[DEBUG] Main content block found (span with id 'ctl00_MainContent_DetailedOutput'): {main_content is not None}")
        
        if not main_content:
            print("[DEBUG] Could not find the main content block on the item page.")
            return None
        
        # Replace <br> tags with newlines for better readability in Discord
        for br in main_content.find_all("br"):
            br.replace_with("\n")
        
        description = main_content.get_text(separator=' ', strip=True)

        # Truncate description if it's too long for a Discord embed (max 4096 characters)
        if len(description) > 4000: # Keeping a buffer for truncation message
            description = description[:4000] + "\n\n... (description truncated)"
            
        return {
            'name': item_name,
            'url': item_page_url,
            'description': description
        }

    except requests.exceptions.RequestException as e:
        print(f"[ERROR] An HTTP error occurred during Archives of Nethys search or item page fetch: {e}")
        return None
    except Exception as e:
        print(f"[ERROR] An unexpected error occurred during Archives of Nethys scraping process: {e}")
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
    # Ignore messages sent by the bot itself
    if message.author == client.user:
        return

    # Check if the message starts with the defined command prefix
    # and has a space after it (e.g., "!aon potion of healing")
    if message.content.startswith(COMMAND_PREFIX + " "):
        # Extract the query after the command prefix
        query = message.content[len(COMMAND_PREFIX)+1:].strip()

        if not query:
            # If no query is provided after the command
            await message.channel.send(f"Please provide an item to search for. Usage: `{COMMAND_PREFIX} <item name>`")
            return

        # Send a temporary "processing" message
        processing_message = await message.channel.send(f"🔍 Searching for `{query}` on the Archives...")
        
        # Perform the search and scrape
        item_data = search_archives_of_nethys(query)
        
        # Delete the "processing" message
        await processing_message.delete()

        if item_data:
            # If item data was successfully found, create and send an embed
            embed = discord.Embed(
                title=item_data['name'],
                url=item_data['url'],
                description=item_data['description'],
                color=discord.Color.dark_red() # A nice color for the embed
            )
            embed.set_footer(text="Data sourced from Archives of Nethys (2e.aonprd.com)")
            await message.channel.send(embed=embed)
        else:
            # If no item data was found or an error occurred during scraping
            await message.channel.send(f"Sorry, I couldn't find an item matching `{query}`. Please check your spelling or try a different term.")

# --- RUN THE BOT ---
if __name__ == "__main__":
    # Ensure the token is available from the environment
    # The bot will not start if the token is not found.
    client.run(TOKEN)
