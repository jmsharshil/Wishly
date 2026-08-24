import re

BIRTHDAY_SYNONYMS = [
    'birthday', 'bday', "b'day", 'birtday', 'birth', 'happybirthday',
    'janamdin', 'janmadin', 'janmdin', 'janmdivas', 'janamdivas', 'varshgaanth', 'varshganth'
]

ANNIVERSARY_SYNONYMS = [
    'anniversary', 'marriageanniversary', 'happyanniversary',
    'salgirah', 'saalgirah', 'shadikisalgirah', 'lagnatithi', 'lagnatidhi'
]

PERSONAL_EVENT_KEYWORDS = [
    'house warming', 'housewarming', 'exam', 'test', 'wedding', 'graduation',
    'baby shower', 'babyshower', 'engagement', 'farewell', 'retirement'
]

def extract_event_details(summary_raw):
    """
    Parses a raw calendar summary/title and extracts the person's name,
    the event type, and whether it's an explicitly formatted personal event.
    Returns: (name, event_type, is_explicit_format)
    """
    summary_lower = summary_raw.lower().replace(" ", "").replace("'", "")
    
    event_type = 'Custom'
    if any(syn in summary_lower for syn in BIRTHDAY_SYNONYMS):
        event_type = 'Birthday'
    elif any(syn in summary_lower for syn in ANNIVERSARY_SYNONYMS):
        event_type = 'Anniversary'
        
    name = summary_raw
    match = re.search(r"^(.*?)['’]s\s+(.+)$", summary_raw, re.IGNORECASE)
    is_explicit_format = False
    
    if match:
        name = match.group(1).strip()
        extracted_type = match.group(2).strip().title()
        is_explicit_format = True
        if event_type == 'Custom':
            event_type = extracted_type
    else:
        # Fallback for exact matches if the regex didn't catch something strange
        if name.lower().endswith(" birthday"):
            name = name[:-9].strip()
            event_type = 'Birthday'
            is_explicit_format = True
        elif name.lower().endswith(" anniversary"):
            name = name[:-12].strip()
            event_type = 'Anniversary'
            is_explicit_format = True
            
        # Extra cleanup just in case
        if name.endswith("'s") or name.endswith("’s"):
            name = name[:-2].strip()
            
    if any(keyword in summary_lower for keyword in PERSONAL_EVENT_KEYWORDS):
        is_explicit_format = True
        
    return name, event_type, is_explicit_format
