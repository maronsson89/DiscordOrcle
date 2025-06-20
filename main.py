import re

# --- [Your existing import + bot setup code here] ---
# Example:
# import discord
# from discord.ext import commands
# bot = commands.Bot(command_prefix="!", intents=discord.Intents.all())
# -----------------------------------------------------

def clean_text(text):
    """
    Cleans the input text by removing common unwanted characters/patterns
    and normalizing whitespace.
    """
    text = re.sub(r'\*\*', '', text) # Remove bold markers
    text = re.sub(r'_+', '', text) # Remove italics markers (e.g., _text_)
    text = re.sub(r'\s+', ' ', text).strip() # Normalize whitespace
    return text

def parse_weapon_stats(text, result):
    """
    Extracts weapon statistics like damage, bulk, hands, and group from the text.
    Uses 'result' as a fallback if information isn't found in the text.
    """
    stats = {}

    # Damage: e.g., "damage 1d6 piercing"
    # Improved regex to handle damage types with spaces (e.g., "piercing or bludgeoning")
    dmg_match = re.search(r'damage\s*(\d+d\d+\s*[\w\s]+)', text, re.IGNORECASE)
    stats['damage'] = dmg_match.group(1).strip() if dmg_match else result.get('damage', 'Unknown')

    # Bulk: e.g., "bulk 1" or "bulk L"
    # More flexible for various bulk representations (numbers, 'L', 'light')
    bulk_match = re.search(r'bulk\s*([\w\d\s\.]+)', text, re.IGNORECASE)
    stats['bulk'] = bulk_match.group(1).strip() if bulk_match else result.get('bulk', 'Unknown')

    # Hands: e.g., "hands 1" or "hands 2+"
    # Catches "1", "2+", or words like "one" (if applicable)
    hands_match = re.search(r'hands\s*(\d[\d\+]*|\w+)', text, re.IGNORECASE)
    stats['hands'] = hands_match.group(1).strip() if hands_match else result.get('hands', '1')

    # Group: e.g., "group sword"
    group_match = re.search(r'group\s*(\w+)', text, re.IGNORECASE)
    stats['group'] = group_match.group(1).strip() if group_match else result.get('group', 'sword') # sensible default

    return stats

def get_critical_specialization_effect(group):
    """
    Returns the critical specialization effect for a given weapon group.
    """
    effects = {
        "axe": "The target is knocked Prone.",
        "bomb": "The target is flat-footed until the start of your next turn.",
        "brawling": "The target is flat-footed until the start of your next turn.",
        "club": "The target is knocked Prone.",
        "dagger": "The target takes 1d6 persistent bleed damage.",
        "dart": "The target takes 1d6 persistent bleed damage.",
        "flail": "The target is knocked Prone.",
        "hammer": "The target is knocked Prone.",
        "knife": "The target takes 1d6 persistent bleed damage.",
        "pick": "The target's AC is reduced by 2 until the start of your next turn.",
        "polearm": "The target is knocked Prone.",
        "shield": "The target is knocked Prone.",
        "sling": "The target is pushed 5 feet away from you.",
        "spear": "The target takes 1d6 persistent bleed damage.",
        "sword": "The target is flat-footed until the start of your next turn.",
        "unarmed": "The target is flat-footed until the start of your next turn.",
        "bow": "The target is pushed 5 feet away from you.",
        "firearm": "The target is pushed 5 feet away from you.",
        "shuriken": "The target is flat-footed until the start of your next turn.",
        "crossbow": "The target is pushed 5 feet away from you.",
        # Add any other groups here as needed
    }
    return effects.get(group.lower(), "No specific critical specialization effect.")

def parse_traits_from_text(text):
    """
    Parses various weapon traits from the input text, handling special cases like
    'versatile' and 'fatal' with their associated data.
    """
    traits = set() # Use a set to automatically handle unique traits and avoid duplicates

    # Patterns for simple traits (no special data needed)
    simple_trait_patterns = [
        r'\bbackswing\b', r'\bdisarm\b', r'\breach\b', r'\btrip\b', r'\bfinesse\b',
        r'\bagile\b', r'\bparry\b', r'\btwo-hand\b', r'\bthrown\b',
        r'\branged\b', r'\bvolley\b', r'\bforceful\b', r'\bshove\b',
        r'\bsweep\b', r'\btwin\b', r'\bmonk\b', r'\bunarmed\b',
        r'\bfree-hand\b', r'\bgrapple\b', r'\bnonlethal\b', r'\bpropulsive\b'
    ]
    for pattern in simple_trait_patterns:
        # Check if the trait exists anywhere in the text
        if re.search(pattern, text, re.IGNORECASE):
            # Add the capitalized version of the matched trait word to the set
            traits.add(re.search(pattern, text, re.IGNORECASE).group(0).title())

    # Handle 'fatal' trait, which can be just 'fatal' or 'fatal dX'
    fatal_match = re.search(r'\bfatal\s*(d\d+)?\b', text, re.IGNORECASE)
    if fatal_match:
        if fatal_match.group(1): # If a dice type (e.g., 'd8') was captured
            traits.add(f"Fatal {fatal_match.group(1).upper()}")
        else: # Just 'fatal' without a specified dice type
            traits.add("Fatal")

    # Handle 'versatile' trait, which can be 'versatile X' (e.g., P, S, B) or just 'versatile'
    # First, find all instances where a type is specified
    versatile_matches = re.findall(r'\bversatile\s*([A-Za-z]+)\b', text, re.IGNORECASE)
    versatile_found = False
    if versatile_matches:
        versatile_found = True
        for match_group in versatile_matches:
            traits.add(f"Versatile {match_group.upper()}")
    
    # Only add plain "Versatile" if no typed versatile was found
    if not versatile_found and re.search(r'\bversatile\b', text, re.IGNORECASE):
        traits.add("Versatile")

    # Convert set to a list and sort for consistent output order
    return sorted(list(traits))

def extract_main_description(text):
    """
    Extracts the main descriptive sentences from the text, filtering out
    metadata and short sentences.
    """
    sentences = text.split('.')
    good_sentences = []
    for sentence in sentences:
        sentence = sentence.strip()
        # Skip sentences containing common metadata keywords
        if any(keyword in sentence.lower() for keyword in [
            'source', 'favored weapon', 'critical specialization',
            'specific magic', 'price', 'bulk', 'hands', 'damage', 'category',
            'certain feats', 'class features', 'weapon runes', 'usage'
        ]):
            continue
        # Skip very short sentences that are unlikely to be descriptive
        if len(sentence) < 15:
            continue
        # Include sentences containing descriptive keywords
        if any(desc_word in sentence.lower() for desc_word in [
            'blade', 'weapon', 'sword', 'known as', 'feet', 'length', 'heavy',
            'edge', 'consist', 'made', 'used', 'designed', 'typically',
            'consists', 'usually', 'common', 'features' # Added more general descriptive terms
        ]):
            good_sentences.append(sentence)
            # Stop after collecting a maximum of 2 descriptive sentences
            if len(good_sentences) >= 2:
                break
    # Join sentences and add a period if necessary
    return '. '.join(good_sentences) + ('.' if good_sentences and not good_sentences[-1].endswith('.') else '') if good_sentences else "A martial weapon used in combat."

def extract_favored_weapon_info(text):
    """
    Extracts information about favored weapons, typically used by deities.
    Looks for a phrase starting with "favored weapon" and ending with a period.
    """
    # Updated regex to skip "of" that typically follows "favored weapon"
    match = re.search(r'favored weapon\s*(?:of\s*)?([A-Z][^.]*?)\.', text, re.IGNORECASE)
    if match:
        txt = match.group(1).strip()
        return re.sub(r'\s+', ' ', txt) # Normalize internal whitespace
    return None

def extract_magic_weapon_info(text):
    """
    Extracts information about specific magic versions of the weapon.
    Looks for a phrase starting with "specific magic" and ending with a period.
    """
    # Regex updated to explicitly look for the end of the sentence (period)
    match = re.search(r'specific magic[^.]*?([A-Z][^.]*?)\.', text, re.IGNORECASE)
    if match:
        txt = match.group(1).strip()
        # Remove leading "Weapons" or "Items" if they appear (common on AON)
        txt = re.sub(r'^(Weapons|Items)\s+', '', txt)
        return re.sub(r'\s+', ' ', txt) # Normalize internal whitespace
    return None

def create_formatted_text_from_result(result, other_results=None):
    """
    Creates a Markdown-formatted text string summarizing weapon information.
    'result' is a dictionary containing weapon data.
    'other_results' is unused in this version, kept for API consistency.
    """
    text = clean_text(result.get('text', '')) # Get and clean the raw text description
    traits = parse_traits_from_text(text)      # Extract traits
    stats = parse_weapon_stats(text, result)   # Extract weapon stats

    lines = [] # List to build output lines

    lines.append("****Item****") # Header for the item block
    name = result.get('name', 'Unknown Item') # Get item name, with fallback
    if result.get('rarity') and result['rarity'].lower() != 'common':
        name += f" ({result['rarity'].title()})" # Add rarity if not common, capitalize it
    lines.append(f"**{name}**") # Bold item name

    # Display traits, or "None" if no traits found
    lines.append("".join([f"［ {t} ］" for t in traits]) if traits else "［ None ］")
    lines.append(f"**Price** {result.get('price', 'Unknown')}")
    lines.append(f"**Bulk** {stats.get('bulk', 'Unknown')}; **Hands** {stats.get('hands', '1')}")
    lines.append(f"**Damage** {stats.get('damage', 'Unknown')}")

    group = stats.get('group', 'unknown') # Get weapon group, with fallback
    
    # Determine weapon category based on text content
    category = 'weapon' # Default category
    
    # First, check for special weapon types
    text_lower = text.lower()
    group_lower = group.lower()
    
    # Detect weapon type
    if 'unarmed' in text_lower or group_lower in ['brawling', 'unarmed']:
        weapon_type = 'unarmed'
    elif 'ammunition' in text_lower or 'ammo' in text_lower:
        weapon_type = 'ammunition'
    elif 'siege' in text_lower or group_lower == 'siege':
        weapon_type = 'siege weapon'
    elif 'alchemical' in text_lower and 'bomb' in text_lower:
        weapon_type = 'alchemical bomb'
    elif group_lower == 'bomb':
        weapon_type = 'bomb'
    elif 'thrown' in text_lower or any(trait.lower() == 'thrown' for trait in traits):
        # Check if it's both thrown and ranged
        if 'ranged' in text_lower or group_lower in ['dart', 'shuriken']:
            weapon_type = 'thrown ranged'
        else:
            weapon_type = 'thrown melee'
    elif 'ranged' in text_lower or group_lower in ['bow', 'crossbow', 'firearm', 'sling']:
        weapon_type = 'ranged'
    else:
        weapon_type = 'melee'
    
    # Check proficiency level
    if 'martial' in text_lower:
        proficiency = 'martial'
    elif 'simple' in text_lower:
        proficiency = 'simple'
    elif 'advanced' in text_lower:
        proficiency = 'advanced'
    else:
        proficiency = None
    
    # Build category string
    if weapon_type in ['ammunition', 'alchemical bomb', 'siege weapon']:
        # These don't typically have proficiency levels
        category = weapon_type
    elif proficiency:
        category = f'{proficiency} {weapon_type} weapon'
    else:
        category = f'{weapon_type} weapon'
    
    lines.append(f"**Category** {category}; **Group** {group.title()}") # Bold category/group, title-case group
    lines.append("⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯") # Separator line

    description = extract_main_description(text)
    lines.append(description) # Add the extracted main description
    if description: # Add a blank line only if there was a description
        lines.append("")

    source = result.get('source', 'Unknown') # Get source, with fallback
    if isinstance(source, list):
        source = source[0] # If source is a list, take the first element
    url = result.get('url', 'https://2e.aonprd.com/') # Get URL, with fallback to AON root
    lines.append(f"📘 **Source:** [{source}]({url})") # Formatted source link
    lines.append("")

    lines.append("****Favored Weapon of****") # Header
    favored = extract_favored_weapon_info(text) # Extract favored weapon info
    if favored:
        # Split by comma and clean each name, filtering out empty strings
        names = [n.strip() for n in favored.split(',') if n.strip()]
        # Create a comma-separated list of linked deity names
        lines.append(', '.join([f"[{n}](https://2e.aonprd.com/Deities.aspx?Name={n.replace(' ', '+')})" for n in names]))
    else:
        lines.append("None") # If no favored weapons found
    lines.append("")

    lines.append(f"****Critical Specialization Effect ({group.title()} Group):****") # Header
    lines.append(get_critical_specialization_effect(group)) # Get and add critical specialization effect
    lines.append("")

    lines.append(f"****Specific Magic {result.get('name', 'Item')}s:****") # Header
    magic = extract_magic_weapon_info(text) # Extract specific magic weapon info
    if magic:
        # Split by comma and clean each name, filtering out empty strings
        names = [n.strip() for n in magic.split(',') if n.strip()]
        # Create a comma-separated list of linked magic item names
        lines.append(', '.join([f"[{n}](https://2e.aonprd.com/Weapons.aspx?Name={n.replace(' ', '+')})" for n in names]))
    else:
        lines.append("None") # If no specific magic items found
    lines.append("")
    lines.append("🔗 Data from the [Archives of Nethys](https://2e.aonprd.com/)") # Footer link to AON
    
    return "\n".join(lines) # Join all lines with newline characters
