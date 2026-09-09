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

import os
import uuid
from azure.storage.blob import BlobServiceClient

def upload_image_to_azure(file_obj, original_filename):
    connection_string = os.environ.get('AZURE_STORAGE_CONNECTION_STRING')
    container_name = os.environ.get('AZURE_STORAGE_CONTAINER_NAME', 'media')

    if not connection_string:
        raise ValueError('AZURE_STORAGE_CONNECTION_STRING is not set')

    blob_service_client = BlobServiceClient.from_connection_string(connection_string)
    
    ext = original_filename.split('.')[-1] if '.' in original_filename else 'jpg'
    blob_name = f'profiles/{uuid.uuid4()}.{ext}'
    
    blob_client = blob_service_client.get_blob_client(container=container_name, blob=blob_name)
    
    # Use content_settings for image content type if needed, but simple upload works:
    blob_client.upload_blob(file_obj, overwrite=True)
    
    return blob_client.url

