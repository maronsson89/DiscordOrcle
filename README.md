# DiscordOrcle
# DiscordOracle - PF2e Discord Bot

A Discord bot for searching Pathfinder 2e content from Archives of Nethys.

## Features

- `/weapon` - Search for weapons
- `/item` - Search for items and equipment
- `/spell` - Search for spells
- `/feat` - Search for feats

## Local Setup

1. Clone this repository
2. Create a `.env` file based on `.env.example`
3. Add your Discord bot token to the `.env` file as `DISCORDORACLE=your_token_here`
4. Install requirements: `pip install -r requirements.txt`
5. Run the bot: `python bot.py`

## Deployment on Render

1. Push this code to GitHub
2. Connect your GitHub repo to Render
3. Set environment variable `DISCORDORACLE` in Render dashboard with your bot token
4. Deploy as a Background Worker
5. Render will securely manage your environment variables

## Adding New Search Types

To add a new search type (e.g., classes, ancestries):

1. Create a new file in `searches/` (e.g., `classes.py`)
2. Copy the structure from an existing search file
3. Modify the category filter and embed fields as needed
4. Import and add a new slash command in `bot.py`

## Environment Variables

- `DISCORDORACLE` - Your Discord bot token (managed securely by Render in production)
