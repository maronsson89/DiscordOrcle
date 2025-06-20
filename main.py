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
    dmg_match = re.search(r'damage\s*(\d+d\d+\s*[\w\s\/]+)', text, re.IGNORECASE)
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
    stats['group'] = group_match.group(1).strip() if group_match else result.get('group', 'Unknown')

    return stats

def get_critical_specialization_effect(group):
    """
    Returns the critical specialization effect for a given weapon group.
    **DATA CORRECTED based on Archives of Nethys**
    """
    effects = {
        "axe": "Choose a second creature adjacent to the original target and within your reach. If its AC is lower than your attack roll result for the critical hit, you deal damage to that creature equal to the result of the weapon's damage die.",
        "bomb": "The target and all other creatures within the splash radius of the bomb take persistent damage of the bomb's damage type equal to the bomb's item bonus to damage.",
        "bow": "If the target of the critical hit is adjacent to a surface, it gets stuck to that surface by the projectile.",
        "brawling": "The target must succeed at a Fortitude save against your class DC or be slowed 1 until the end of your next turn.",
        "club": "You knock the target away from you up to 10 feet (you choose the distance). This is forced movement.",
        "crossbow": "The target is immobilized and can't use actions with the move trait until the end of your next turn.",
        "dart": "The target takes 1d6 persistent bleed damage.",
        "firearm": "The target must succeed at a Fortitude save against your class DC or be stunned 1.",
        "flail": "The target is knocked prone.",
        "hammer": "The target is knocked prone.",
        "knife": "The target takes 1d6 persistent bleed damage.",
        "pick": "The weapon viciously pierces the target, who takes 2 additional damage per weapon damage die.",
        "polearm": "The target is moved 5 feet in a direction of your choice. This is forced movement.",
        "shield": "You knock the target prone.",
        "sling": "The target must succeed at a Fortitude save against your class DC or be stunned 1.",
        "spear": "The weapon pierces the target, pinning them in place. The target is immobilized and can't use actions with the move trait until the end of your next turn.",
        "sword": "The target is made flat-footed until the start of your next turn.",
        "unarmed": "The target must succeed at a Fortitude save against your class DC or be slowed 1 until the end of your next turn."
    }
    return effects.get(group.lower(), "No specific critical specialization effect found for this group.")

def parse_traits_from_text(text):
    """
    Parses various weapon traits from the input text, handling special cases like
    'versatile' and 'fatal' with their associated data.
    **LOGIC IMPROVED to find more traits and be more efficient**
    """
    traits = set() # Use a set to automatically handle unique traits and avoid duplicates

    # Patterns for simple traits (no special data needed)
    simple_trait_patterns = [
        r'\bagile\b', r'\battached\b', r'\bbackstabber\b', r'\bbackswing\b',
        r'\bconcussive\b', r'\bdeadly-simple\b', r'\bdisarm\b', r'\bfinesse\b',
        r'\bforceful\b', r'\bfree-hand\b', r'\bgrapple\b', r'\binjured\b',
        r'\bnonlethal\b', r'\bparry\b', r'\bpropulsive\b', r'\bshove\b',
        r'\bsweep\b', r'\btethered\b', r'\btrip\b', r'\btwin\b', r'\bunarmed\b',
        r'\bmonk\b', r'\bcobbled\b' # Added more traits
    ]
    for pattern in simple_trait_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            # Add the capitalized version of the matched trait word to the set
            traits.add(match.group(0).title())

    # Handle traits with dice values (e.g., fatal d8, deadly d10)
    valued_dice_patterns = [r'\bfatal\s*(d\d+)\b', r'\bdeadly\s*(d\d+)\b']
    for pattern in valued_dice_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            trait_name = pattern.split('\\b')[1].title() # e.g., "Fatal"
            traits.add(f"{trait_name} {match.group(1).upper()}")

    # Handle traits with distance values (e.g., thrown 20 ft., reach 10 feet, volley 30 ft.)
    ranged_patterns = [r'\bthrown(?!\-)\s*(\d+\s*f(ee|oo)?t\.?)?\b', r'\bvolley\s*(\d+\s*f(ee|oo)?t\.?)?\b', r'\breach\s*(\d+\s*f(ee|oo)?t\.?)?\b']
    for pattern in ranged_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            trait_name = pattern.split('\\b')[1].title()
            if match.group(1): # If a distance was captured
                traits.add(f"{trait_name} {match.group(1).strip()}")
            else: # Just the trait name
                traits.add(trait_name)
    
    # Handle 'two-hand' which might have a damage die
    two_hand_match = re.search(r'\btwo-hand\s*(d\d+)\b', text, re.IGNORECASE)
    if two_hand_match:
        traits.add(f"Two-Hand {two_hand_match.group(1).upper()}")
    elif re.search(r'\btwo-hand\b', text, re.IGNORECASE):
        traits.add("Two-Hand")

    # Handle 'versatile' trait, which can be 'versatile X' (e.g., P, S, B) or just 'versatile'
    versatile_matches = re.findall(r'\bversatile\s+([PSB])\b', text, re.IGNORECASE)
    if versatile_matches:
        for match_group in versatile_matches:
            traits.add(f"Versatile {match_group.upper()}")
    elif re.search(r'\bversatile\b', text, re.IGNORECASE) and not any('Versatile' in t for t in traits):
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
            'certain feats', 'class features', 'weapon runes', 'usage', 'traits'
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
    return '. '.join(good_sentences) + ('.' if good_sentences and not good_sentences[-1].endswith('.') else '') if good_sentences else "A standard weapon used in combat."

def extract_favored_weapon_info(text):
    """
    Extracts information about favored weapons, typically used by deities.
    Looks for a phrase starting with "favored weapon" and ending with a period.
    """
    # Regex updated to explicitly look for the end of the sentence (period)
    match = re.search(r'favored weapon[^.]*?([A-Z][^.]*?)\.', text, re.IGNORECASE)
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
    traits = parse_traits_from_text(text)     # Extract traits
    stats = parse_weapon_stats(text, result)  # Extract weapon stats

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
    # Determine weapon category based on text content (martial, simple, or default)
    category = 'melee weapon' # Default category
    if 'martial' in text.lower():
        category = 'martial melee weapon'
    elif 'simple' in text.lower():
        category = 'simple melee weapon'
    elif 'advanced' in text.lower(): # Added advanced weapon check
        category = 'advanced melee weapon'
    
    lines.append(f"**Category** {category}; **Group** {group.title()}") # Bold category/group, title-case group
    lines.append("⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯") # Separator line

    description = extract_main_description(text)
    lines.append(description) # Add the extracted main description
    if description and len(description) > 1: # Add a blank line only if there was a description
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
