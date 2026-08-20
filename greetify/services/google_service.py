import os
import datetime
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from greetify.models import Event

SCOPES = [
    'https://www.googleapis.com/auth/calendar.events',
    'https://www.googleapis.com/auth/contacts',
    'https://www.googleapis.com/auth/userinfo.profile',
    'https://www.googleapis.com/auth/userinfo.email',
    'openid'
]

def get_google_auth_url():
    """Returns the Google OAuth login URL."""
    # To be implemented when client secrets are added
    pass

def handle_google_callback(code):
    """Exchanges auth code for tokens and fetches user info."""
    # To be implemented
    pass

def _get_google_calendar_service(user):
    profile = user.profile
    if not profile.google_access_token:
        return None

    creds = Credentials(
        token=profile.google_access_token,
        refresh_token=profile.google_refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ.get('GOOGLE_CLIENT_ID'),
        client_secret=os.environ.get('GOOGLE_CLIENT_SECRET'),
    )
    
    try:
        return build('calendar', 'v3', credentials=creds)
    except Exception as e:
        print(f"Failed to build Google Calendar service: {e}")
        return None

def _get_google_people_service(user):
    profile = user.profile
    if not profile.google_access_token:
        return None

    creds = Credentials(
        token=profile.google_access_token,
        refresh_token=profile.google_refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ.get('GOOGLE_CLIENT_ID'),
        client_secret=os.environ.get('GOOGLE_CLIENT_SECRET'),
    )
    
    try:
        return build('people', 'v1', credentials=creds)
    except Exception as e:
        print(f"Failed to build Google People service: {e}")
        return None

def fetch_events_from_google(user):
    """Fetches upcoming events and birthdays for the user."""
    service = _get_google_calendar_service(user)
    if not service:
        return {"error": "no_account_linked", "message": "Google account is not linked or token is missing."}

    now = datetime.datetime.utcnow().isoformat() + 'Z'
    next_year = (datetime.datetime.utcnow() + datetime.timedelta(days=365)).isoformat() + 'Z'

    calendars_to_sync = ['primary', 'addressbook#contacts@group.v.calendar.google.com']
    synced_count = 0
    fetched_google_ids = []
    
    # Pre-fetch Google Contacts to get phone numbers for birthday calendar events
    people_service = _get_google_people_service(user)
    contact_phone_map_exact = {}
    contact_phone_map_name = {}
    
    if people_service:
        try:
            results = people_service.people().connections().list(
                resourceName='people/me',
                personFields='names,phoneNumbers,birthdays,events',
                pageSize=1000
            ).execute()
            connections = results.get('connections', [])
            for person in connections:
                names = person.get('names', [])
                phones = person.get('phoneNumbers', [])
                birthdays = person.get('birthdays', [])
                events_list = person.get('events', [])
                
                valid_dates = []
                for b in birthdays:
                    if 'date' in b:
                        valid_dates.append(b['date'])
                for e in events_list:
                    if 'date' in e:
                        valid_dates.append(e['date'])
                        
                if names and phones:
                    name_str = names[0].get('displayName', '').strip().lower()
                    phone_val = phones[0].get('value', '')
                    
                    if name_str:
                        contact_phone_map_name[name_str] = phone_val
                    
                    if valid_dates:
                        for date_info in valid_dates:
                            month = date_info.get('month')
                            day = date_info.get('day')
                            
                            if month and day:
                                # Create a unique key using Name + Month + Day
                                name_key = f"{name_str}_{month}_{day}"
                                contact_phone_map_exact[name_key] = phone_val
        except Exception as e:
            from googleapiclient.errors import HttpError
            if isinstance(e, HttpError) and e.resp.status in [401, 403]:
                return {"error": "permission_denied", "message": "don't have permission to access of calender or contacts"}
            print(f"Failed to fetch contacts for phone mapping: {e}")

    for calendar_id in calendars_to_sync:
        try:
            events_result = service.events().list(
                calendarId=calendar_id, 
                timeMin=now,
                timeMax=next_year,
                maxResults=100, 
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            events = events_result.get('items', [])

            import re
            
            for item in events:
                summary_raw = item.get('summary', 'Unknown')
                summary = summary_raw.lower()
                is_birthday_cal = calendar_id != 'primary'
                
                description = item.get('description', '')
                contact_number = None
                tags = ''
                notes_for_ai = ''
                
                if description:
                    # Look for a number with 10 to 15 digits (optional leading +)
                    match = re.search(r'\+?\d{10,15}', description)
                    if match:
                        contact_number = match.group(0)
                        description = description.replace(contact_number, '')
                        
                    # Extract hashtags as tags
                    hashtags = re.findall(r'#(\w+)', description)
                    if hashtags:
                        tags = ", ".join(hashtags)
                        description = re.sub(r'#\w+', '', description)
                        
                    # The remaining text is notes for AI
                    notes_for_ai = description.strip()
                
                # Determine event type based on keywords, otherwise fallback to Custom
                event_type = 'Custom'
                summary_lower = summary_raw.lower().replace(" ", "").replace("'", "")
                
                birthday_synonyms = [
                    'birthday', 'bday', 'birtday', 'birth', 'happybirthday',
                    'janamdin', 'janmadin', 'janmdivas', 'janamdivas', 'varshgaanth', 'varshganth'
                ]
                anniversary_synonyms = [
                    'anniversary', 'marriageanniversary', 'happyanniversary',
                    'salgirah', 'saalgirah', 'shadikisalgirah', 'lagnatithi', 'lagnatidhi'
                ]
                
                if is_birthday_cal or any(syn in summary_lower for syn in birthday_synonyms):
                    event_type = 'Birthday'
                elif any(syn in summary_lower for syn in anniversary_synonyms):
                    event_type = 'Anniversary'
                
                # Clean up the name and extract custom event types (e.g., "Pranjal's Graduation")
                name = summary_raw
                match = re.search(r"^(.*?)'s\s+(.+)$", summary_raw, re.IGNORECASE)
                
                if match:
                    name = match.group(1).strip()
                    extracted_type = match.group(2).strip().title()
                    
                    # If it wasn't already identified as Birthday or Anniversary, use the extracted custom type
                    if event_type == 'Custom':
                        event_type = extracted_type
                else:
                    # Fallback for exact matches if the regex didn't catch something strange
                    if name.lower().endswith(" birthday"):
                        name = name[:-9].strip()
                    elif name.lower().endswith(" anniversary"):
                        name = name[:-12].strip()
                        
                if is_birthday_cal and not contact_number:
                    clean_name = name.strip().lower()
                    start_date_str = item.get('start', {}).get('date')
                    
                    # 1. Try Exact match with Date
                    if start_date_str:
                        try:
                            dt = datetime.datetime.strptime(start_date_str, "%Y-%m-%d")
                            exact_key = f"{clean_name}_{dt.month}_{dt.day}"
                            if exact_key in contact_phone_map_exact:
                                contact_number = contact_phone_map_exact[exact_key]
                        except Exception:
                            pass
                            
                    # 2. Try Exact Name match (fallback)
                    if not contact_number and clean_name in contact_phone_map_name:
                        contact_number = contact_phone_map_name[clean_name]
                        
                    # 3. Try Partial match (fallback) - Is contact name inside the raw calendar summary?
                    if not contact_number:
                        for c_name, c_phone in contact_phone_map_name.items():
                            if c_name and len(c_name) > 2 and c_name in summary_lower:
                                contact_number = c_phone
                                break
                
                start = item['start'].get('date') or item['start'].get('dateTime')
                if not start:
                    continue
                
                # Convert to YYYY-MM-DD
                date_str = start[:10]
                google_id = item['id']
                fetched_google_ids.append(google_id)

                source_val = 'GOOGLE_CONTACTS' if is_birthday_cal else 'GOOGLE_CALENDAR'

                # Check if event already exists
                existing_event = Event.objects.filter(user=user, google_event_id=google_id).first()
                dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
                
                if not existing_event:
                    # Deduplicate: If an event with the same name, date, and type exists (e.g. from a different calendar/contact)
                    existing_event = Event.objects.filter(user=user, name__iexact=name, date__month=dt.month, date__day=dt.day, event_type=event_type).first()
                
                if not existing_event and contact_number:
                    # Deduplicate: If an event with the same contact number, date, and type exists
                    existing_event = Event.objects.filter(user=user, contact_number=contact_number, date__month=dt.month, date__day=dt.day, event_type=event_type).first()

                if not existing_event:
                    event = Event.objects.create(
                        user=user,
                        name=name,
                        date=date_str,
                        event_type=event_type,
                        google_event_id=google_id,
                        contact_number=contact_number,
                        tags=tags,
                        notes_for_ai=notes_for_ai,
                        source=source_val
                    )
                    synced_count += 1
                    
                    # Generate wish automatically for the fetched event
                    try:
                        from greetify.services.ai_service import generate_wish
                        from greetify.models import WishHistory
                        generated_text = generate_wish(event, 'EN')
                        WishHistory.objects.create(
                            user=user,
                            event=event,
                            generated_text=generated_text,
                            language='EN',
                            status='GENERATED'
                        )
                    except Exception as e:
                        print(f"Failed to auto-generate wish for synced event: {e}")
                else:
                    # If it exists, update it if name or date changed
                    has_changes = False
                    if existing_event.name != name:
                        existing_event.name = name
                        has_changes = True
                    if str(existing_event.date) != date_str:
                        existing_event.date = date_str
                        has_changes = True
                    if contact_number and existing_event.contact_number != contact_number:
                        existing_event.contact_number = contact_number
                        has_changes = True
                        number_added = True
                    else:
                        number_added = False
                        
                    if tags and existing_event.tags != tags:
                        existing_event.tags = tags
                        has_changes = True
                    if notes_for_ai and existing_event.notes_for_ai != notes_for_ai:
                        existing_event.notes_for_ai = notes_for_ai
                        has_changes = True
                    if existing_event.source != source_val:
                        existing_event.source = source_val
                        has_changes = True
                        
                    if has_changes:
                        existing_event.save()
                        synced_count += 1
                        
                        if number_added and existing_event.google_event_id and existing_event.source == 'GOOGLE_CALENDAR':
                            push_event_to_google(user, existing_event)
                        
        except Exception as e:
            from googleapiclient.errors import HttpError
            if isinstance(e, HttpError) and e.resp.status in [401, 403]:
                return {"error": "permission_denied", "message": "don't have permission to access of calender or contacts"}
            print(f"Error fetching from calendar {calendar_id}: {e}")
            continue

    # Cleanup deleted events: 
    # If an event exists in our DB with a google_event_id, and its date is >= today, 
    # but it was not fetched from Google, it means it was deleted on Google.
    today_str = datetime.datetime.utcnow().date().isoformat()
    Event.objects.filter(
        user=user,
        google_event_id__isnull=False,
        date__gte=today_str
    ).exclude(
        google_event_id__in=fetched_google_ids
    ).delete()
            
    return synced_count

def push_event_to_google(user, event):
    """Creates or updates an event in Google Calendar."""
    service = _get_google_calendar_service(user)
    if not service:
        return False
        
    summary = f"{event.name}'s {event.event_type.title()}"
    
    # Construct the description from the event's fields
    description_parts = []
    if event.contact_number:
        description_parts.append(event.contact_number)
        
    if event.tags:
        hashtag_string = " ".join([f"#{t.strip()}" for t in event.tags.split(',')])
        description_parts.append(hashtag_string)
        
    if event.notes_for_ai:
        description_parts.append(event.notes_for_ai)
        
    description_text = "\n".join(description_parts).strip()
    if not description_text:
        description_text = "Created by Wishing App"

    # Construct event body
    event_body = {
        'summary': summary,
        'description': description_text,
        'start': {
            'date': str(event.date),
        },
        'end': {
            'date': str(event.date),
        }
    }
    
    # We will create an annual recurring event for birthdays/anniversaries.
    # However, if the event ID contains an underscore (e.g. 'xyz_20260812'), 
    # it means this is a specific instance of a recurring event, not the master.
    # Google Calendar API throws a 400 Bad Request if we try to add an RRULE to an instance.
    is_recurring_instance = bool(event.google_event_id and '_' in event.google_event_id)
    
    if not is_recurring_instance:
        event_body['recurrence'] = ['RRULE:FREQ=YEARLY']
    
    try:
        if event.google_event_id:
            # Update existing
            updated_event = service.events().update(
                calendarId='primary',
                eventId=event.google_event_id,
                body=event_body
            ).execute()
        else:
            # Create new
            created_event = service.events().insert(
                calendarId='primary',
                body=event_body
            ).execute()
            
            # Save the ID back to our DB
            event.google_event_id = created_event['id']
            event.save()
            
        return True
    except Exception as e:
        print(f"Failed to push event to Google Calendar: {e}")
        return False

def delete_event_from_google(user, google_event_id):
    """Deletes an event from Google Calendar."""
    if not google_event_id:
        return False
        
    service = _get_google_calendar_service(user)
    if not service:
        return False
        
    try:
        service.events().delete(
            calendarId='primary',
            eventId=google_event_id
        ).execute()
        return True
    except Exception as e:
        print(f"Failed to delete event from Google Calendar: {e}")
        return False

def push_contact_to_google(user, event):
    """Creates or updates a contact in Google Contacts with the event date."""
    service = _get_google_people_service(user)
    if not service:
        return False

    contact_body = {
        "names": [{"givenName": event.name}],
    }
    
    if event.contact_number:
        contact_body["phoneNumbers"] = [{"value": event.contact_number}]
    
    date_dict = {
        "year": event.date.year,
        "month": event.date.month,
        "day": event.date.day,
    }

    if event.event_type == 'Birthday':
        contact_body["birthdays"] = [{"date": date_dict}]
    elif event.event_type == 'Anniversary':
        contact_body["events"] = [{"date": date_dict, "type": "anniversary"}]

    try:
        if event.google_contact_id:
            # Updating a contact requires the current resourceName and etag
            resource_name = event.google_contact_id
            contact = service.people().get(resourceName=resource_name, personFields="names,birthdays,events,phoneNumbers").execute()
            
            contact_body['etag'] = contact.get('etag')
            
            updated_contact = service.people().updateContact(
                resourceName=resource_name,
                updatePersonFields="names,birthdays,events,phoneNumbers",
                body=contact_body
            ).execute()
        else:
            created_contact = service.people().createContact(
                body=contact_body
            ).execute()
            
            event.google_contact_id = created_contact.get('resourceName')
            event.save()
            
        return True
    except Exception as e:
        print(f"Failed to push contact to Google Contacts: {e}")
        return False

def delete_contact_from_google(user, google_contact_id):
    """Deletes a contact from Google Contacts."""
    if not google_contact_id:
        return False
        
    service = _get_google_people_service(user)
    if not service:
        return False
        
    try:
        service.people().deleteContact(
            resourceName=google_contact_id
        ).execute()
        return True
    except Exception as e:
        print(f"Failed to delete contact from Google Contacts: {e}")
        return False
