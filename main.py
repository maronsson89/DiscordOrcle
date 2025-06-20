
# main.py - Fixed version for PF2e Discord Bot (Plain Text Output)

# — [imports and setup code trimmed for brevity] —
# Insert your existing import + bot setup code here

# Replace or insert below functions:

def parse_traits_from_text(text):
    traits = []
    trait_patterns = [
        r'\bbackswing\b', r'\bdisarm\b', r'\breach\b', r'\btrip\b', r'\bfinesse\b',
        r'\bagile\b', r'\bdeadly\b', r'\bfatal\b', r'\bversatile\s*([A-Za-z])\b', r'\bparry\b',
        r'\btwo-hand\b', r'\bthrown\b', r'\branged\b', r'\bvolley\b', r'\bforceful\b',
        r'\bshove\b', r'\bsweep\b', r'\btwin\b', r'\bmonk\b', r'\bunarmed\b',
        r'\bfree-hand\b', r'\bgrapple\b', r'\bnonlethal\b', r'\bpropulsive\b'
    ]
    for pattern in trait_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            trait_name = match.group(0)
            if 'versatile' in trait_name.lower():
                versatile_match = re.search(r'versatile\s*([A-Za-z])\b', text, re.IGNORECASE)
                if versatile_match:
                    damage_type = versatile_match.group(1).upper()
                    traits.append(f"Versatile {damage_type}")
                else:
                    traits.append("Versatile")
                continue
            traits.append(trait_name.title())
    return list(set(traits))

def extract_main_description(text):
    sentences = text.split('.')
    good_sentences = []
    for sentence in sentences:
        sentence = sentence.strip()
        if any(keyword in sentence.lower() for keyword in [
            'source', 'favored weapon', 'critical specialization',
            'specific magic', 'price', 'bulk', 'hands', 'damage', 'category',
            'certain feats', 'class features', 'weapon runes'
        ]):
            continue
        if len(sentence) < 15:
            continue
        if any(desc_word in sentence.lower() for desc_word in [
            'blade', 'weapon', 'sword', 'known as', 'feet', 'length', 'heavy',
            'edge', 'consist', 'made', 'used', 'designed'
        ]):
            good_sentences.append(sentence)
            if len(good_sentences) >= 2:
                break
    return '. '.join(good_sentences) + '.' if good_sentences else "A martial weapon used in combat."

def extract_favored_weapon_info(text):
    match = re.search(r'favored weapon[^.]*?([A-Z][^.]*)', text, re.IGNORECASE)
    if match:
        txt = match.group(1).strip()
        return re.sub(r'\s+', ' ', txt)
    return None

def extract_magic_weapon_info(text):
    match = re.search(r'specific magic[^.]*?([A-Z][^.]*)', text, re.IGNORECASE)
    if match:
        txt = match.group(1).strip()
        txt = re.sub(r'^(Weapons|Items)\s+', '', txt)
        return re.sub(r'\s+', ' ', txt)
    return None

def create_formatted_text_from_result(result, other_results=None):
    text = clean_text(result.get('text', ''))
    traits = parse_traits_from_text(text)
    stats = parse_weapon_stats(text, result)
    lines = []

    lines.append("****Item****")
    name = result['name']
    if result.get('rarity') and result['rarity'].lower() != 'common':
        name += f" ({result['rarity']})"
    lines.append(f"**{name}**")

    lines.append("".join([f"［ {t} ］" for t in traits]) if traits else "None")
    lines.append(f"**Price** {result.get('price', 'Unknown')}")
    lines.append(f"**Bulk** {stats.get('bulk', 'Unknown')}; **Hands** {stats.get('hands', '1')}")
    lines.append(f"**Damage** {stats.get('damage', 'Unknown')}")

    group = stats.get('group', 'unknown')
    category = 'martial melee weapon' if 'martial' in text.lower() else 'melee weapon'
    lines.append(f"**Category** {category}; **Group** {group}")
    lines.append("⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯")

    lines.append(extract_main_description(text))
    lines.append("")

    source = result.get('source', 'Unknown')
    if isinstance(source, list): source = source[0]
    url = result.get('url', 'https://2e.aonprd.com/')
    lines.append(f"📘 **Source:** [{source}]({url})")
    lines.append("")

    lines.append("****Favored Weapon of****")
    favored = extract_favored_weapon_info(text)
    if favored:
        names = [n.strip() for n in favored.split(',')]
        lines.append(', '.join([f"[{n}](https://2e.aonprd.com/Deities.aspx?Name={n.replace(' ', '+')})" for n in names]))
    else:
        lines.append("None")
    lines.append("")

    lines.append(f"****Critical Specialization Effect ({group.title()} Group):****")
    lines.append(get_critical_specialization_effect(group))
    lines.append("")

    lines.append(f"****Specific Magic {result['name']}s:****")
    magic = extract_magic_weapon_info(text)
    if magic:
        names = [n.strip() for n in magic.split(',')]
        lines.append(', '.join([f"[{n}](https://2e.aonprd.com/Weapons.aspx?Name={n.replace(' ', '+')})" for n in names]))
    else:
        lines.append("None")
    lines.append("")
    lines.append("🔗 Data from the [Archives of Nethys](https://2e.aonprd.com/)")
    return "\n".join(lines)
