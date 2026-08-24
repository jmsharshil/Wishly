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

def get_google_credentials(user):
    profile = user.profile
    if not profile.google_access_token:
        return None
    return Credentials(
        token=profile.google_access_token,
        refresh_token=profile.google_refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ.get('GOOGLE_CLIENT_ID'),
        client_secret=os.environ.get('GOOGLE_CLIENT_SECRET'),
    )

def _save_creds_if_refreshed(user, creds):
    if creds and creds.token and creds.token != user.profile.google_access_token:
        user.profile.google_access_token = creds.token
        user.profile.save()

def _get_google_calendar_service(user, creds=None):
    if not creds:
        creds = get_google_credentials(user)
    if not creds:
        return None
    
    try:
        return build('calendar', 'v3', credentials=creds)
    except Exception as e:
        print(f"Failed to build Google Calendar service: {e}")
        return None

def _get_google_people_service(user, creds=None):
    if not creds:
        creds = get_google_credentials(user)
    if not creds:
        return None
    
    try:
        return build('people', 'v1', credentials=creds)
    except Exception as e:
        print(f"Failed to build Google People service: {e}")
        return None

def fetch_events_from_google(user):
    """Fetches upcoming events and birthdays for the user."""
    creds = get_google_credentials(user)
    service = _get_google_calendar_service(user, creds=creds)
    if not service:
        return {"error": "no_account_linked", "message": "Google account is not linked or token is missing."}

    # Fetch events starting from 2 days ago to avoid timezone boundaries dropping today's completed events
    time_min = (datetime.datetime.utcnow() - datetime.timedelta(days=2)).isoformat() + 'Z'
    time_max = (datetime.datetime.utcnow() + datetime.timedelta(days=365)).isoformat() + 'Z'

    calendars_to_sync = ['primary', 'addressbook#contacts@group.v.calendar.google.com']
    synced_count = 0
    fetched_google_ids = []
    
    # Pre-fetch Google Contacts to get phone numbers for birthday calendar events
    people_service = _get_google_people_service(user, creds=creds)
    contact_phone_map_exact = {}
    contact_phone_map_name = {}
    contact_original_year_map = {}
    
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
                        
                if names:
                    name_str = names[0].get('displayName', '').strip().lower()
                    
                    phone_val = phones[0].get('value', '') if phones else None
                    if phone_val:
                        import re
                        phone_val = re.sub(r'[^\d+]', '', phone_val)
                        
                    if name_str and phone_val:
                        contact_phone_map_name[name_str] = phone_val
                    
                    if valid_dates:
                        for date_info in valid_dates:
                            month = date_info.get('month')
                            day = date_info.get('day')
                            year = date_info.get('year')
                            
                            if month and day:
                                # Create a unique key using Name + Month + Day
                                name_key = f"{name_str}_{month}_{day}"
                                if phone_val:
                                    contact_phone_map_exact[name_key] = phone_val
                                if year:
                                    contact_original_year_map[name_key] = year
        except Exception as e:
            from googleapiclient.errors import HttpError
            from google.auth.exceptions import RefreshError
            if isinstance(e, HttpError) and e.resp.status in [401, 403]:
                _save_creds_if_refreshed(user, creds)
                return {"error": "permission_denied", "message": "don't have permission to access of calender or contacts"}
            if isinstance(e, RefreshError):
                _save_creds_if_refreshed(user, creds)
                return {"error": "permission_denied", "message": "Session expired, please login again"}
            print(f"Failed to fetch contacts for phone mapping: {e}")

    sync_success = True
    
    # Pre-fetch existing events to avoid N+1 queries during sync
    existing_events = list(Event.objects.filter(user=user))
    existing_by_google_id = {e.google_event_id: e for e in existing_events if e.google_event_id}
    existing_by_name_md = {}
    existing_by_name_ymd = {}
    existing_by_phone_md = {}
    
    for e in existing_events:
        name_lower = e.name.strip().lower()
        if e.event_type in ['Birthday', 'Anniversary']:
            existing_by_name_md[(name_lower, e.date.month, e.date.day)] = e
            if e.contact_number:
                import re
                std_phone = re.sub(r'[^\d+]', '', e.contact_number)
                existing_by_phone_md[(std_phone, e.date.month, e.date.day)] = e
        else:
            existing_by_name_ymd[(name_lower, e.date.year, e.date.month, e.date.day)] = e

    for calendar_id in calendars_to_sync:
        try:
            from greetify.models import DeletedEventLog
            deleted_ids = set(DeletedEventLog.objects.filter(user=user).values_list('external_id', flat=True))
            
            events_result = service.events().list(
                calendarId=calendar_id, 
                timeMin=time_min,
                timeMax=time_max,
                maxResults=100, 
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            events = events_result.get('items', [])

            import re
            processed_master_ids = set()
            
            for item in events:
                google_id = item.get('id')
                master_id = item.get('recurringEventId') or google_id
                
                if master_id in deleted_ids or google_id in deleted_ids:
                    continue
                    
                if master_id in processed_master_ids:
                    continue
                processed_master_ids.add(master_id)
                    
                summary_raw = item.get('summary', 'Unknown')
                summary = summary_raw.lower()
                is_birthday_cal = calendar_id != 'primary'
                
                description = item.get('description') or ''
                contact_number = None
                tags = ''
                notes_for_ai = ''
                
                if description:
                    # Look for a number with 10 to 15 digits (optional leading +, spaces, dashes, parentheses)
                    match = re.search(r'\+?(?:\d[\s\-\(\)]*){10,15}', description)
                    if match:
                        raw_number = match.group(0)
                        # clean the number to just digits and +
                        cleaned_number = re.sub(r'[^\d+]', '', raw_number)
                        # verify it actually has 10-15 digits
                        if 10 <= len(re.sub(r'\D', '', cleaned_number)) <= 15:
                            contact_number = cleaned_number
                            description = description.replace(raw_number, '')
                        
                    # Extract hashtags as tags
                    hashtags = re.findall(r'#(\w+)', description)
                    if hashtags:
                        tags = ", ".join(hashtags)
                        description = re.sub(r'#\w+', '', description)
                        
                    # The remaining text is notes for AI
                    notes_for_ai = description.strip()
                
                from greetify.utils import extract_event_details
                name, event_type, is_explicit_format = extract_event_details(summary_raw)

                # Finally, if it's from contacts and we still couldn't figure it out, assume Birthday
                if event_type == 'Custom' and is_birthday_cal:
                    event_type = 'Birthday'
                        
                start = item['start'].get('date') or item['start'].get('dateTime')
                if not start:
                    continue
                
                # Convert to YYYY-MM-DD
                date_str = start[:10]
                fetched_google_ids.append(master_id)

                source_val = 'GOOGLE_CONTACTS' if is_birthday_cal else 'GOOGLE_CALENDAR'
                try:
                    dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
                except ValueError:
                    continue
                    
                if is_birthday_cal and not contact_number:
                    clean_name = name.strip().lower()
                    
                    # 1. Try Exact match with Date
                    exact_key = f"{clean_name}_{dt.month}_{dt.day}"
                    if exact_key in contact_phone_map_exact:
                        contact_number = contact_phone_map_exact[exact_key]
                            
                    # 2. Try Exact Name match (fallback)
                    if not contact_number and clean_name in contact_phone_map_name:
                        contact_number = contact_phone_map_name[clean_name]
                        
                    # 3. Try Partial match (fallback) - Is contact name inside the raw calendar summary?
                    if not contact_number:
                        summary_lower = summary_raw.lower()
                        for c_name, c_phone in contact_phone_map_name.items():
                            if c_name and len(c_name) > 2:
                                if re.search(rf'\b{re.escape(c_name)}\b', summary_lower):
                                    contact_number = c_phone
                                    break

                # Check if event already exists by master_id, or fallback to instance id for backward compatibility
                existing_event = existing_by_google_id.get(master_id)
                if not existing_event:
                    existing_event = existing_by_google_id.get(google_id)
                    
                has_original_year = False
                if event_type in ['Birthday', 'Anniversary']:
                    exact_key = f"{name.strip().lower()}_{dt.month}_{dt.day}"
                    if exact_key in contact_original_year_map:
                        orig_year = contact_original_year_map[exact_key]
                        date_str = f"{orig_year:04d}-{dt.month:02d}-{dt.day:02d}"
                        dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
                        has_original_year = True
                        
                if not existing_event:
                    # Deduplicate: If an event with the same name, date, and type exists (e.g. from a different calendar/contact)
                    clean_name_match = name.strip().lower()
                    if event_type in ['Birthday', 'Anniversary']:
                        existing_event = existing_by_name_md.get((clean_name_match, dt.month, dt.day))
                        if not existing_event and contact_number:
                            import re
                            std_phone = re.sub(r'[^\d+]', '', contact_number)
                            existing_event = existing_by_phone_md.get((std_phone, dt.month, dt.day))
                    else:
                        existing_event = existing_by_name_ymd.get((clean_name_match, dt.year, dt.month, dt.day))

                if not existing_event:
                    event = Event.objects.create(
                        user=user,
                        name=name,
                        date=date_str,
                        event_type=event_type,
                        google_event_id=master_id,
                        contact_number=contact_number,
                        tags=tags,
                        notes_for_ai=notes_for_ai,
                        source=source_val
                    )
                    synced_count += 1
                    
                    if master_id:
                        existing_by_google_id[master_id] = event
                    clean_name_match = name.strip().lower()
                    if event_type in ['Birthday', 'Anniversary']:
                        existing_by_name_md[(clean_name_match, dt.month, dt.day)] = event
                        if contact_number:
                            existing_by_phone_md[(contact_number, dt.month, dt.day)] = event
                    else:
                        existing_by_name_ymd[(clean_name_match, dt.year, dt.month, dt.day)] = event
                    
                    # Generate wish automatically for the fetched event in the background
                    from greetify.views import async_generate_wish
                    async_generate_wish(user.id, event.id)
                else:
                    # If it exists, update it if name or date changed
                    has_changes = False
                    if existing_event.google_event_id != master_id:
                        existing_event.google_event_id = master_id
                        has_changes = True
                    if existing_event.name != name:
                        existing_event.name = name
                        has_changes = True
                    if str(existing_event.date) != date_str:
                        new_dt = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
                        
                        if existing_event.event_type in ['Birthday', 'Anniversary'] and not has_original_year:
                            # Preserve the original year we have in DB, just update month/day if they changed
                            try:
                                orig_year = existing_event.date.year if not isinstance(existing_event.date, str) else int(existing_event.date[:4])
                                updated_date = datetime.date(orig_year, new_dt.month, new_dt.day)
                                
                                curr_date = existing_event.date
                                if isinstance(curr_date, str):
                                    curr_date = datetime.datetime.strptime(curr_date, "%Y-%m-%d").date()
                                    
                                if curr_date != updated_date:
                                    existing_event.date = updated_date
                                    has_changes = True
                            except Exception as e:
                                print(f"Error preserving original year for event {existing_event.id}: {e}")
                                pass
                        else:
                            # Update full date (since it's a one-time event or we have the TRUE original year)
                            existing_event.date = new_dt
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
                    if existing_event.source != source_val and existing_event.source != 'APP':
                        existing_event.source = source_val
                        has_changes = True
                        
                    if has_changes:
                        existing_event.save()
                        synced_count += 1
                        
                        if number_added and existing_event.google_event_id and existing_event.source == 'GOOGLE_CALENDAR':
                            push_event_to_google(user, existing_event)
                        
        except Exception as e:
            from googleapiclient.errors import HttpError
            from google.auth.exceptions import RefreshError
            sync_success = False
            if isinstance(e, HttpError) and e.resp.status in [401, 403]:
                _save_creds_if_refreshed(user, creds)
                return {"error": "permission_denied", "message": "don't have permission to access of calender or contacts"}
            if isinstance(e, RefreshError):
                _save_creds_if_refreshed(user, creds)
                return {"error": "permission_denied", "message": "Session expired, please login again"}
            print(f"Error fetching from calendar {calendar_id}: {e}")
            continue

    # Cleanup deleted events: 
    # If an event exists in our DB with a google_event_id, and its date is >= today, 
    # but it was not fetched from Google, it means it was deleted on Google.
    if sync_success:
        today_str = datetime.datetime.utcnow().date().isoformat()
        Event.objects.filter(
            user=user,
            google_event_id__isnull=False,
            date__gte=today_str
        ).exclude(
            google_event_id__in=fetched_google_ids
        ).delete()
            
    _save_creds_if_refreshed(user, creds)
    return synced_count

def push_event_to_google(user, event):
    """Creates or updates an event in Google Calendar."""
    creds = get_google_credentials(user)
    service = _get_google_calendar_service(user, creds=creds)
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
            
        _save_creds_if_refreshed(user, creds)
        return True
    except Exception as e:
        print(f"Failed to push event to Google Calendar: {e}")
        _save_creds_if_refreshed(user, creds)
        return False

def delete_event_from_google(user, google_event_id):
    """Deletes an event from Google Calendar."""
    if not google_event_id:
        return False
        
    creds = get_google_credentials(user)
    service = _get_google_calendar_service(user, creds=creds)
    if not service:
        return False
        
    try:
        service.events().delete(
            calendarId='primary',
            eventId=google_event_id
        ).execute()
        _save_creds_if_refreshed(user, creds)
        return True
    except Exception as e:
        print(f"Failed to delete event from Google Calendar: {e}")
        _save_creds_if_refreshed(user, creds)
        return False

def push_contact_to_google(user, event):
    """Creates or updates a contact in Google Contacts with the event date."""
    creds = get_google_credentials(user)
    service = _get_google_people_service(user, creds=creds)
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
            
            # Preserve existing names to prevent overriding when multiple events share the same contact number
            if contact.get('names'):
                contact_body['names'] = contact.get('names')
            
            # Also preserve existing birthdays and events to avoid deleting them when adding a new one
            if contact.get('birthdays') and 'birthdays' in contact_body:
                contact_body['birthdays'] = contact.get('birthdays') + contact_body['birthdays']
            elif contact.get('birthdays'):
                contact_body['birthdays'] = contact.get('birthdays')
                
            if contact.get('events') and 'events' in contact_body:
                contact_body['events'] = contact.get('events') + contact_body['events']
            elif contact.get('events'):
                contact_body['events'] = contact.get('events')
            
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
            
        _save_creds_if_refreshed(user, creds)
        return True
    except Exception as e:
        print(f"Failed to push contact to Google Contacts: {e}")
        _save_creds_if_refreshed(user, creds)
        return False

def delete_contact_from_google(user, google_contact_id):
    """Deletes a contact from Google Contacts."""
    if not google_contact_id:
        return False
        
    creds = get_google_credentials(user)
    service = _get_google_people_service(user, creds=creds)
    if not service:
        return False
        
    try:
        service.people().deleteContact(
            resourceName=google_contact_id
        ).execute()
        _save_creds_if_refreshed(user, creds)
        return True
    except Exception as e:
        print(f"Failed to delete contact from Google Contacts: {e}")
        _save_creds_if_refreshed(user, creds)
        return False
