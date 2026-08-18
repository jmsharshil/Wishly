from rest_framework import viewsets, status
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.authtoken.models import Token
from django.contrib.auth.models import User
from .models import UserProfile, Event, WishHistory
from .serializers import UserProfileSerializer, EventSerializer, WishHistorySerializer, AppleAuthSerializer
from .services.ai_service import generate_wish
from .services.google_service import fetch_events_from_google, push_event_to_google, delete_event_from_google, push_contact_to_google, delete_contact_from_google
from .services.apple_service import verify_apple_id_token
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from django.utils import timezone
import os
import datetime
from datetime import timedelta
import urllib.parse
import requests
import jwt
from rest_framework import mixins, filters
from rest_framework.pagination import PageNumberPagination
from django.db.models import Q

class StandardResultsSetPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 100
@api_view(['GET'])
def google_auth_url(request):
    """Returns the URL for Google OAuth login."""
    client_id = os.environ.get('GOOGLE_CLIENT_ID')
    redirect_uri = 'http://127.0.0.1:8000/api/auth/google/callback/'
    
    base_url = "https://accounts.google.com/o/oauth2/v2/auth"
    params = {
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': 'openid email profile https://www.googleapis.com/auth/calendar.events',
        'access_type': 'offline',
        'prompt': 'consent'
    }
    
    url = f"{base_url}?{urllib.parse.urlencode(params)}"
    return Response({'url': url})

@api_view(['POST'])
def google_auth_callback(request):
    """Handles the callback and logs in the user."""
    code = request.data.get('code')
    if not code:
        return Response({'error': 'Code is required'}, status=status.HTTP_400_BAD_REQUEST)

    client_id = os.environ.get('GOOGLE_CLIENT_ID')
    client_secret = os.environ.get('GOOGLE_CLIENT_SECRET')
    redirect_uri = 'http://127.0.0.1:8000/api/auth/google/callback/'

    # Exchange code for token
    token_url = "https://oauth2.googleapis.com/token"
    token_data = {
        'code': code,
        'client_id': client_id,
        'client_secret': client_secret,
        'redirect_uri': redirect_uri,
        'grant_type': 'authorization_code'
    }
    
    token_response = requests.post(token_url, data=token_data)
    if not token_response.ok:
        return Response({'error': 'Failed to fetch token from Google', 'details': token_response.json()}, status=status.HTTP_400_BAD_REQUEST)

    tokens = token_response.json()
    access_token = tokens.get('access_token')
    refresh_token = tokens.get('refresh_token')

    # Fetch user info
    user_info_url = "https://www.googleapis.com/oauth2/v2/userinfo"
    headers = {'Authorization': f'Bearer {access_token}'}
    user_info_response = requests.get(user_info_url, headers=headers)
    
    if not user_info_response.ok:
        return Response({'error': 'Failed to fetch user info'}, status=status.HTTP_400_BAD_REQUEST)

    user_info = user_info_response.json()
    email = user_info.get('email')
    username = email.split('@')[0] if email else 'user'
    
    if not email:
        return Response({'error': 'Email not provided by Google'}, status=status.HTTP_400_BAD_REQUEST)

    # Get or create User
    user, created = User.objects.get_or_create(email=email, defaults={'username': email})
    
    # Get or create UserProfile
    profile, p_created = UserProfile.objects.get_or_create(user=user)
    profile.google_access_token = access_token
    if refresh_token:
        profile.google_refresh_token = refresh_token
    if 'picture' in user_info:
        profile.profile_picture = user_info['picture']
    profile.save()

    # Create DRF Token
    token, _ = Token.objects.get_or_create(user=user)

    return Response({
        'token': token.key,
        'user': {
            'email': user.email,
            'name': user_info.get('name'),
            'profile_picture': profile.profile_picture
        }
    })

@api_view(['POST'])
def google_auth_mobile(request):
    """Handles login for mobile apps using direct access_token."""
    access_token = request.data.get('access_token')
    
    if not access_token:
        return Response({'error': 'Access token is required'}, status=status.HTTP_400_BAD_REQUEST)

    # Fetch user info directly using the token provided by the mobile app
    user_info_url = "https://www.googleapis.com/oauth2/v2/userinfo"
    headers = {'Authorization': f'Bearer {access_token}'}
    user_info_response = requests.get(user_info_url, headers=headers)
    
    if not user_info_response.ok:
        return Response({'error': 'Invalid access token'}, status=status.HTTP_400_BAD_REQUEST)

    user_info = user_info_response.json()
    email = user_info.get('email')
    
    if not email:
        return Response({'error': 'Email not provided by Google'}, status=status.HTTP_400_BAD_REQUEST)
        
    # Get or create User and UserProfile as you did before
    user, created = User.objects.get_or_create(email=email, defaults={'username': email.split('@')[0]})
    profile, p_created = UserProfile.objects.get_or_create(user=user)
    
    profile.google_access_token = access_token
    if 'picture' in user_info:
        profile.profile_picture = user_info['picture']
    # Note: Mobile SDKs typically handle refresh_token automatically, 
    # but if needed, you can pass it from the app and save it here.
    profile.save()

    # Create DRF Token
    token, _ = Token.objects.get_or_create(user=user)

    return Response({
        'token': token.key,
        'user': {
            'id': user.id,
            'email': user.email,
            'name': user_info.get('name') or user.username,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'phone_number': profile.phone_number,
            'profile_picture': profile.profile_picture
        }
    })

class AppleAuthVerifyView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = AppleAuthSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        id_token = serializer.validated_data['id_token']
        phone_number = serializer.validated_data.get('phone_number')
        first_name = serializer.validated_data.get('first_name', '')
        last_name = serializer.validated_data.get('last_name', '')
        
        # Verify identity token
        apple_data = verify_apple_id_token(id_token)
        apple_id = apple_data['apple_id']
        email = apple_data['email']
        
        first_name = first_name or apple_data.get('first_name', '')
        last_name = last_name or apple_data.get('last_name', '')
        
        user = None
        
        # A. Find existing user linked to this Apple Account
        try:
            profile = UserProfile.objects.get(apple_user_id=apple_id)
            user = profile.user
        except UserProfile.DoesNotExist:
            pass
            
        # B. Find existing user matching email & link Apple ID
        if not user and email:
            try:
                user = User.objects.get(email=email)
                profile, _ = UserProfile.objects.get_or_create(user=user)
                if not profile.apple_user_id:
                    profile.apple_user_id = apple_id
                    profile.save()
            except User.DoesNotExist:
                pass
                
        # C. Create new user if not found
        if not user:
            # Create a new user profile
            username = email.split('@')[0] if email else (phone_number or apple_id[:10])
            
            # Ensure unique username
            base_username = username
            counter = 1
            while User.objects.filter(username=username).exists():
                username = f"{base_username}{counter}"
                counter += 1
                
            user = User.objects.create(
                username=username,
                email=email or '',
                first_name=first_name,
                last_name=last_name
            )
            profile = UserProfile.objects.create(
                user=user,
                apple_user_id=apple_id,
                phone_number=phone_number
            )
            
        # Create DRF Token
        token, _ = Token.objects.get_or_create(user=user)
        
        return Response({
            'token': token.key,
            'user': {
                'id': user.id,
                'email': user.email,
                'name': f"{user.first_name} {user.last_name}".strip() or user.username,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'phone_number': user.profile.phone_number if hasattr(user, 'profile') else None,
                'profile_picture': user.profile.profile_picture if hasattr(user, 'profile') else None
            }
        }, status=status.HTTP_200_OK)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_profile(request):
    """Returns the current user's profile."""
    profile, created = UserProfile.objects.get_or_create(user=request.user)
    serializer = UserProfileSerializer(profile)
    return Response(serializer.data)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_dashboard(request):
    """Returns dashboard stats."""
    today = timezone.now().date()
    
    # User Profile
    profile, created = UserProfile.objects.get_or_create(user=request.user)
    profile_data = UserProfileSerializer(profile).data
    
    # Fetch all events to handle recurring annual events correctly (birthdays, etc.)
    all_events = Event.objects.filter(user=request.user)
    
    events_today = []
    upcoming_events_list = []
    
    for event in all_events:
        try:
            # Calculate next occurrence in the current year
            next_date = event.date.replace(year=today.year)
            if next_date < today:
                # If it already passed this year, next occurrence is next year
                next_date = next_date.replace(year=today.year + 1)
        except ValueError:
            # Handle leap year (Feb 29) on non-leap years
            if event.date.month == 2 and event.date.day == 29:
                next_date = datetime.date(today.year, 3, 1)
                if next_date < today:
                    next_date = datetime.date(today.year + 1, 3, 1)
            else:
                continue
                
        days_until = (next_date - today).days
        
        if days_until == 0:
            events_today.append(event)
        elif 0 < days_until <= 30:
            upcoming_events_list.append((days_until, event))
            
    upcoming_events_list.sort(key=lambda x: x[0])
    
    events_today_ids = [e.id for e in events_today]
    events_today_count = len(events_today)
    
    # Number of today's events that have a SENT wish
    wishes_sent_for_today = WishHistory.objects.filter(
        user=request.user,
        status='SENT',
        event_id__in=events_today_ids
    ).values('event').distinct().count()
    
    # Total wishes sent overall
    total_sent = WishHistory.objects.filter(
        user=request.user,
        status='SENT'
    ).count()
    
    upcoming_events_count = len(upcoming_events_list)
    upcoming_events_qs = [item[1] for item in upcoming_events_list[:5]]
    upcoming_events_data = EventSerializer(upcoming_events_qs, many=True).data
    
    # Recent Wishes (Last 5)
    recent_wishes_qs = WishHistory.objects.filter(
        user=request.user,
        event__isnull=False
    ).order_by('-created_at')[:5]
    recent_wishes_data = WishHistorySerializer(recent_wishes_qs, many=True).data

    return Response({
        'user_profile': profile_data,
        'limit': {
            'total_events_today': events_today_count,
            'wishes_sent_today': wishes_sent_for_today,
        },
        'stats': {
            'total_wishes_sent': total_sent,
            'upcoming_events_count': upcoming_events_count,
            'streak': 12, # Mock streak
        },
        'upcoming_events': upcoming_events_data,
        'recent_wishes': recent_wishes_data
    })

class EventViewSet(viewsets.ModelViewSet):
    """CRUD API for Events."""
    serializer_class = EventSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardResultsSetPagination

    def _get_cleaned_filter_types(self, user):
        distinct_types = Event.objects.filter(user=user).values_list('event_type', flat=True).distinct()
        
        cleaned_types = set()
        birthday_synonyms = ['birthday', 'bday', 'birtday', 'birth', 'happybirthday', 'janamdin', 'janmadin', 'janmdivas', 'janamdivas', 'varshgaanth', 'varshganth']
        anniversary_synonyms = ['anniversary', 'marriageanniversary', 'happyanniversary', 'salgirah', 'saalgirah', 'shadikisalgirah', 'lagnatithi', 'lagnatidhi']
        
        for t in distinct_types:
            if not t: continue
            val_lower = t.lower().replace(" ", "").replace("'", "")
            if val_lower in birthday_synonyms:
                cleaned_types.add('Birthday')
            elif val_lower in anniversary_synonyms:
                cleaned_types.add('Anniversary')
            else:
                cleaned_types.add(" ".join(t.split()).title())
                
        default_types = {'Birthday', 'Anniversary'}
        return sorted(list(default_types.union(cleaned_types)))

    def get_queryset(self):
        queryset = Event.objects.filter(user=self.request.user)
        event_type = self.request.query_params.get('event_type')
        
        if event_type:
            val_lower = event_type.lower().replace(" ", "").replace("'", "")
            birthday_synonyms = ['birthday', 'bday', 'birtday', 'birth', 'happybirthday', 'janamdin', 'janmadin', 'janmdivas', 'janamdivas', 'varshgaanth', 'varshganth']
            anniversary_synonyms = ['anniversary', 'marriageanniversary', 'happyanniversary', 'salgirah', 'saalgirah', 'shadikisalgirah', 'lagnatithi', 'lagnatidhi']
            
            if val_lower in birthday_synonyms:
                q_objects = Q(event_type__iexact='Birthday')
                for syn in birthday_synonyms:
                    q_objects |= Q(event_type__iexact=syn)
                queryset = queryset.filter(q_objects)
            elif val_lower in anniversary_synonyms:
                q_objects = Q(event_type__iexact='Anniversary')
                for syn in anniversary_synonyms:
                    q_objects |= Q(event_type__iexact=syn)
                queryset = queryset.filter(q_objects)
            else:
                clean_type = " ".join(event_type.split()).title()
                queryset = queryset.filter(Q(event_type__iexact=clean_type) | Q(event_type__iexact=event_type))
                
        # Name filtering (handles single and comma-separated multiple)
        names = self.request.query_params.get('name')
        if names:
            name_list = [n.strip() for n in names.split(',') if n.strip()]
            if name_list:
                name_q = Q()
                for n in name_list:
                    name_q |= Q(name__icontains=n)
                queryset = queryset.filter(name_q)
                
        # Date filtering (handles single and comma-separated multiple)
        dates = self.request.query_params.get('date')
        if dates:
            date_list = [d.strip() for d in dates.split(',') if d.strip()]
            if date_list:
                # Note: expects standard YYYY-MM-DD format from the frontend query
                queryset = queryset.filter(date__in=date_list)
                
        # Search filtering
        search_query = self.request.query_params.get('search')
        if search_query:
            queryset = queryset.filter(
                Q(name__icontains=search_query) |
                Q(event_type__icontains=search_query) |
                Q(notes_for_ai__icontains=search_query)
            )

        return queryset.order_by('date')

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        
        # Inject the filters array into the paginated response
        if isinstance(response.data, dict):
            response.data['filters'] = self._get_cleaned_filter_types(request.user)
            
        return response

    @action(detail=False, methods=['get'])
    def filters(self, request):
        """Returns a list of all distinct event types created by this user."""
        return Response(self._get_cleaned_filter_types(request.user))

    def perform_create(self, serializer):
        event = serializer.save(user=self.request.user)
        push_event_to_google(self.request.user, event)
        push_contact_to_google(self.request.user, event)
        
        # Automatically generate a wish upon event creation
        try:
            generated_text = generate_wish(event, 'EN')
            WishHistory.objects.create(
                user=self.request.user,
                event=event,
                generated_text=generated_text,
                language='EN',
                status='GENERATED'
            )
        except Exception as e:
            print(f"Failed to auto-generate wish: {e}")

    def perform_update(self, serializer):
        event = serializer.save()
        push_event_to_google(self.request.user, event)
        push_contact_to_google(self.request.user, event)

    def perform_destroy(self, instance):
        if instance.google_event_id:
            delete_event_from_google(self.request.user, instance.google_event_id)
        if instance.google_contact_id:
            delete_contact_from_google(self.request.user, instance.google_contact_id)
        instance.delete()

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def sync_google_events(request):
    """Triggers sync with Google Calendar/Contacts."""
    synced_count = fetch_events_from_google(request.user)
    return Response({
        'status': 'success',
        'message': f'Successfully synced {synced_count} events from Google Calendar.',
        'synced_count': synced_count
    })

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def generate_ai_wish(request):
    """Generates an AI wish based on event ID."""
    event_id = request.data.get('event_id')
    language = request.data.get('language', 'EN')
    
    try:
        event = Event.objects.get(id=event_id, user=request.user)
    except Event.DoesNotExist:
        return Response({'error': 'Event not found'}, status=status.HTTP_404_NOT_FOUND)

    generated_text = generate_wish(event, language)
    
    wish = WishHistory.objects.create(
        user=request.user,
        event=event,
        generated_text=generated_text,
        language=language,
        status='GENERATED'
    )
    
    serializer = WishHistorySerializer(wish)
    return Response(serializer.data)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def mark_wish_sent(request, pk):
    """Marks a wish as SENT."""
    try:
        wish = WishHistory.objects.get(id=pk, user=request.user)
    except WishHistory.DoesNotExist:
        return Response({'error': 'Wish not found'}, status=status.HTTP_404_NOT_FOUND)

    wish.status = 'SENT'
    wish.save()
    
    return Response({'status': 'Wish marked as sent'})

@api_view(['PUT', 'PATCH'])
@permission_classes([IsAuthenticated])
def edit_wish(request, pk):
    """Manually edit the text of a generated wish."""
    try:
        wish = WishHistory.objects.get(id=pk, user=request.user)
    except WishHistory.DoesNotExist:
        return Response({'error': 'Wish not found'}, status=status.HTTP_404_NOT_FOUND)

    new_text = request.data.get('generated_text')
    if not new_text:
        return Response({'error': 'generated_text is required'}, status=status.HTTP_400_BAD_REQUEST)
        
    wish.generated_text = new_text
    wish.save()
    
    serializer = WishHistorySerializer(wish)
    return Response(serializer.data)

class WishHistoryViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet):
    """API to view and delete wish history."""
    serializer_class = WishHistorySerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        queryset = WishHistory.objects.filter(user=self.request.user, status='SENT')
        time_filter = self.request.query_params.get('filter')
        search_query = self.request.query_params.get('search')
        
        if time_filter:
            today = timezone.now().date()
            if time_filter == 'today':
                queryset = queryset.filter(created_at__date=today)
            elif time_filter == 'this_week':
                start_of_week = today - timedelta(days=today.weekday())
                queryset = queryset.filter(created_at__date__gte=start_of_week)
            elif time_filter == 'this_month':
                queryset = queryset.filter(created_at__year=today.year, created_at__month=today.month)
                
        if search_query:
            # Search across generated text or event name
            queryset = queryset.filter(
                Q(generated_text__icontains=search_query) | 
                Q(event__name__icontains=search_query)
            )
                
        return queryset.order_by('-created_at')

class AppleSyncView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        user = request.user
        contacts_data = request.data.get('contacts', [])
        events_data = request.data.get('events', [])
        
        # Build a map of contact names to full contact info
        contact_map = {}
        for contact_info in contacts_data:
            given_name = contact_info.get('givenName', '')
            family_name = contact_info.get('familyName', '')
            
            full_name = f"{given_name} {family_name}".strip().lower()
            if full_name:
                contact_map[full_name] = contact_info
            if given_name:
                contact_map[given_name.lower()] = contact_info

        # Process Calendar Events
        for event_info in events_data:
            import re
            external_id = event_info.get('id')
            title = event_info.get('title', 'Untitled Event')
            start_date = event_info.get('startDate')
            notes = event_info.get('notes', '')

            date_str = None
            if start_date:
                date_str = start_date[:10]  # Extract YYYY-MM-DD from ISO string

            if not date_str:
                continue

            summary_lower = title.lower().replace(" ", "").replace("'", "")
            
            birthday_synonyms = [
                'birthday', 'bday', 'birtday', 'birth', 'happybirthday',
                'janamdin', 'janmadin', 'janmdivas', 'janamdivas', 'varshgaanth', 'varshganth'
            ]
            anniversary_synonyms = [
                'anniversary', 'marriageanniversary', 'happyanniversary',
                'salgirah', 'saalgirah', 'shadikisalgirah', 'lagnatithi', 'lagnatidhi'
            ]
            
            event_type = 'Custom'
            if any(syn in summary_lower for syn in birthday_synonyms):
                event_type = 'Birthday'
            elif any(syn in summary_lower for syn in anniversary_synonyms):
                event_type = 'Anniversary'

            # Extract name from title (e.g. "Pranjal's Birthday" or "Pranjal’s Birthday" -> "Pranjal")
            name = title
            match = re.search(r"^(.*?)['’]s\s+(.+)$", title, re.IGNORECASE)
            is_explicit_format = False
            
            if match:
                name = match.group(1).strip()
                extracted_type = match.group(2).strip().title()
                is_explicit_format = True
                if event_type == 'Custom':
                    event_type = extracted_type
            else:
                if name.lower().endswith(" birthday"):
                    name = name[:-9].strip()
                    is_explicit_format = True
                elif name.lower().endswith(" anniversary"):
                    name = name[:-12].strip()
                    is_explicit_format = True
                    
                # Extra cleanup just in case
                if name.endswith("'s") or name.endswith("’s"):
                    name = name[:-2].strip()
                    
            # Allow common personal events even without the 's format
            personal_event_keywords = [
                'house warming', 'housewarming', 'exam', 'test', 'wedding', 'graduation',
                'baby shower', 'babyshower', 'engagement', 'farewell', 'retirement'
            ]
            if any(keyword in summary_lower for keyword in personal_event_keywords):
                is_explicit_format = True
                    
            # Skip generic calendar events (like festivals, meetings) if they don't look like personal events
            if event_type == 'Custom' and not is_explicit_format:
                continue

            # Find phone number and notes from contact
            contact_number = None
            contact_notes = ''
            clean_name = name.strip().lower()
            
            matched_contact = None
            if clean_name in contact_map:
                matched_contact = contact_map[clean_name]
            else:
                # Try partial match inside the full title
                for c_name, c_info in contact_map.items():
                    if c_name and len(c_name) > 2 and c_name in summary_lower:
                        matched_contact = c_info
                        break
                        
            if matched_contact:
                phones = matched_contact.get('phoneNumbers', [])
                if phones:
                    contact_number = phones[0]
                # Some iOS libraries use 'note' (singular) while others use 'notes'
                contact_notes = matched_contact.get('note', matched_contact.get('notes', ''))
                
            # Combine calendar notes with contact notes
            final_notes = notes
            if contact_notes:
                final_notes = f"{final_notes}\n{contact_notes}".strip()

            source_val = 'APPLE_CONTACTS' if contact_number else 'APPLE_CALENDAR'

            existing_event = Event.objects.filter(user=user, apple_event_id=external_id).first()
            
            import datetime
            dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
            
            if not existing_event:
                existing_event = Event.objects.filter(user=user, name__iexact=name, date__month=dt.month, date__day=dt.day, event_type=event_type).first()
            if not existing_event and contact_number:
                existing_event = Event.objects.filter(user=user, contact_number=contact_number, date__month=dt.month, date__day=dt.day, event_type=event_type).first()

            if not existing_event:
                event = Event.objects.create(
                    user=user,
                    apple_event_id=external_id,
                    name=name,
                    date=date_str,
                    contact_number=contact_number,
                    event_type=event_type,
                    notes_for_ai=final_notes,
                    source=source_val
                )
            else:
                existing_event.name = name
                existing_event.date = date_str
                existing_event.notes_for_ai = final_notes
                existing_event.event_type = event_type
                existing_event.source = source_val
                if contact_number:
                    existing_event.contact_number = contact_number
                existing_event.save()
                event = existing_event
                
            # Auto-generate wish if it doesn't have one yet!
            from greetify.models import WishHistory
            has_wish = WishHistory.objects.filter(user=user, event=event).exists()
            if not has_wish:
                try:
                    from greetify.services.ai_service import generate_wish
                    generated_text = generate_wish(event, 'EN')
                    WishHistory.objects.create(
                        user=user,
                        event=event,
                        generated_text=generated_text,
                        language='EN',
                        status='GENERATED'
                    )
                except Exception as e:
                    print(f"Failed to auto-generate wish for Apple synced event: {e}")

        return Response({
            "message": "Apple data synced successfully",
            "contacts_received": len(contacts_data),
            "events_synced": len(events_data)
        }, status=status.HTTP_200_OK)

