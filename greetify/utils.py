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
    """
    Uploads a file-like object to Azure Blob Storage and returns its public URL.
    Reads config from AZURE_ACCOUNT_NAME, AZURE_ACCOUNT_KEY, AZURE_MEDIA_CONTAINER,
    and (optionally) AZURE_CUSTOM_DOMAIN.
    """
    account_name = os.environ.get('AZURE_ACCOUNT_NAME')
    account_key = os.environ.get('AZURE_ACCOUNT_KEY')
    container_name = os.environ.get('AZURE_MEDIA_CONTAINER', 'media')

    if not account_name or not account_key:
        raise ValueError('AZURE_ACCOUNT_NAME / AZURE_ACCOUNT_KEY are not set')

    connection_string = (
        f"DefaultEndpointsProtocol=https;"
        f"AccountName={account_name};"
        f"AccountKey={account_key};"
        f"EndpointSuffix=core.windows.net"
    )

    blob_service_client = BlobServiceClient.from_connection_string(connection_string)

    # Create the container automatically if it doesn't exist yet
    container_client = blob_service_client.get_container_client(container_name)
    if not container_client.exists():
        container_client.create_container()

    ext = original_filename.split('.')[-1] if '.' in original_filename else 'jpg'
    blob_name = f'profiles/{uuid.uuid4()}.{ext}'

    blob_client = blob_service_client.get_blob_client(container=container_name, blob=blob_name)

    # Ensure the stream is at the start in case something upstream already read it
    file_obj.seek(0)
    blob_client.upload_blob(file_obj, overwrite=True)

    # Prefer the custom domain for the returned URL if one is configured
    custom_domain = os.environ.get('AZURE_CUSTOM_DOMAIN')
    if custom_domain:
        return f"https://{custom_domain}/{container_name}/{blob_name}"
    return blob_client.url

def pretty_name_from_username(username, email=None):
    """
    Builds a presentable display name when the user has no first/last name
    set (e.g. Google/Apple sign-in that never filled in a name).
    """
    raw = username or ''
    if email and '@' in email:
        raw = email.split('@')[0]

    cleaned = re.sub(r'[._\-]+', ' ', raw)
    cleaned = re.sub(r'\d+', ' ', cleaned).strip()
    cleaned = re.sub(r'\s+', ' ', cleaned)

    if not cleaned:
        return 'User'

    return cleaned.title()