from django.db import models
from django.contrib.auth.models import User

class UserProfile(models.Model):
    SUBSCRIPTION_CHOICES = [
        ('FREE', 'Free'),
        ('PRO', 'Pro'),
        ('ELITE', 'Elite'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    google_access_token = models.CharField(max_length=2048, blank=True, null=True)
    google_refresh_token = models.CharField(max_length=2048, blank=True, null=True)
    apple_user_id = models.CharField(max_length=255, blank=True, null=True, unique=True, help_text="Apple ID 'sub' claim")
    phone_number = models.CharField(max_length=20, blank=True, null=True, unique=True)
    profile_picture = models.URLField(blank=True, null=True)
    subscription_tier = models.CharField(max_length=10, choices=SUBSCRIPTION_CHOICES, default='FREE')

    def __str__(self):
        return self.user.username


class Event(models.Model):

    SOURCE_CHOICES = [
        ('APP', 'App'),
        ('GOOGLE_CALENDAR', 'Google Calendar'),
        ('GOOGLE_CONTACTS', 'Google Contacts'),
        ('APPLE_CALENDAR', 'Apple Calendar'),
        ('APPLE_CONTACTS', 'Apple Contacts'),
    ]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='events')
    source = models.CharField(max_length=50, choices=SOURCE_CHOICES, default='APP')
    name = models.CharField(max_length=255)
    contact_number = models.CharField(max_length=20, blank=True, null=True, help_text="WhatsApp or phone number")
    profile_picture = models.URLField(blank=True, null=True, help_text="URL to the person's profile picture")
    date = models.DateField()
    event_type = models.CharField(max_length=50, default='Birthday')
    notes_for_ai = models.TextField(blank=True, help_text="Notes for AI generation (e.g., 'loves poetry')")
    tags = models.CharField(max_length=255, blank=True, help_text="Comma-separated tags (e.g., 'Family,Close')")
    google_event_id = models.CharField(max_length=255, blank=True, null=True, help_text="ID from Google Calendar")
    google_contact_id = models.CharField(max_length=255, blank=True, null=True, help_text="ID from Google Contacts (People API)")
    apple_event_id = models.CharField(max_length=255, blank=True, null=True, help_text="ID from Apple Calendar")
    apple_contact_id = models.CharField(max_length=255, blank=True, null=True, help_text="ID from Apple Contacts")

    def __str__(self):
        return f"{self.name} - {self.event_type} on {self.date}"


class WishHistory(models.Model):
    STATUS_CHOICES = [
        ('GENERATED', 'Generated'),
        ('SENT', 'Sent'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='wishes')
    event = models.ForeignKey(Event, on_delete=models.CASCADE, null=True, related_name='wishes')
    generated_text = models.TextField()
    language = models.CharField(max_length=10, default='EN')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='GENERATED')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Wish for {self.event.name if self.event else 'Unknown'} - {self.status}"
