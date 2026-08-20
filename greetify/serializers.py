from rest_framework import serializers
from django.contrib.auth.models import User
from .models import UserProfile, Event, WishHistory

class UserProfileSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    email = serializers.CharField(source='user.email', read_only=True)

    class Meta:
        model = UserProfile
        fields = ('username', 'email', 'profile_picture', 'subscription_tier', 'last_login_provider')

class FlexibleDateField(serializers.DateField):
    def to_internal_value(self, value):
        if isinstance(value, str):
            # iOS keyboards often auto-replace '-' with '–' (en-dash) or '—' (em-dash)
            value = value.replace('–', '-').replace('—', '-')
        return super().to_internal_value(value)

class EventSerializer(serializers.ModelSerializer):
    generated_wish_preview = serializers.SerializerMethodField()
    generated_wish_id = serializers.SerializerMethodField()
    user_profile_picture = serializers.SerializerMethodField()
    
    date = FlexibleDateField(
        input_formats=[
            'iso-8601', '%Y-%m-%d', 
            '%d/%m/%Y', '%d-%m-%Y', 
            '%m/%d/%Y', '%m-%d-%Y', 
            '%d %b %Y', '%d %B %Y', 
            '%b %d %Y', '%B %d %Y', 
            '%b %d, %Y', '%B %d, %Y',
            '%d.%m.%Y'
        ]
    )

    class Meta:
        model = Event
        fields = '__all__'
        read_only_fields = ('user',)

    def get_generated_wish_preview(self, obj):
        # Fetch the most recent wish generated for this event
        latest_wish = obj.wishes.order_by('-created_at').first()
        if latest_wish:
            return latest_wish.generated_text
        return None

    def get_generated_wish_id(self, obj):
        latest_wish = obj.wishes.order_by('-created_at').first()
        if latest_wish:
            return latest_wish.id
        return None

    def get_user_profile_picture(self, obj):
        if hasattr(obj.user, 'profile'):
            return obj.user.profile.profile_picture
        return None

    def validate_event_type(self, value):
        if not value:
            return value
        
        # Remove spaces/quotes and lowercase for matching
        val_lower = value.lower().replace(" ", "").replace("'", "")
        
        # Birthday variations (English, Hindi, Gujarati, etc.)
        birthday_synonyms = [
            'birthday', 'bday', 'birtday', 'birth', 'happybirthday',
            'janamdin', 'janmadin', 'janmdivas', 'janamdivas', 'varshgaanth', 'varshganth'
        ]
        if val_lower in birthday_synonyms:
            return 'Birthday'
            
        # Anniversary variations
        anniversary_synonyms = [
            'anniversary', 'marriageanniversary', 'happyanniversary',
            'salgirah', 'saalgirah', 'shadikisalgirah', 'lagnatithi', 'lagnatidhi'
        ]
        if val_lower in anniversary_synonyms:
            return 'Anniversary'
            
        # For all other custom events, clean up whitespace and capitalize the first letters
        return " ".join(value.split()).title()

class WishHistorySerializer(serializers.ModelSerializer):
    event_details = EventSerializer(source='event', read_only=True)
    user_profile_picture = serializers.SerializerMethodField()

    class Meta:
        model = WishHistory
        fields = '__all__'
        read_only_fields = ('user', 'status', 'created_at')

    def get_user_profile_picture(self, obj):
        if hasattr(obj.user, 'profile'):
            return obj.user.profile.profile_picture
        return None

class AppleAuthSerializer(serializers.Serializer):
    id_token = serializers.CharField(required=True, help_text="Apple ID Token from frontend SDK")
    phone_number = serializers.CharField(
        required=False, 
        allow_blank=True, 
        help_text="Verified phone number from step 1 (needed for registration/linking)"
    )
    first_name = serializers.CharField(required=False, allow_blank=True, default="")
    last_name = serializers.CharField(required=False, allow_blank=True, default="")
