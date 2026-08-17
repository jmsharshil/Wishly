from django.contrib import admin
from .models import UserProfile, Event, WishHistory

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'subscription_tier')

@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ('name', 'user', 'event_type', 'date')
    list_filter = ('event_type', 'date')
    search_fields = ('name', 'user__username')

@admin.register(WishHistory)
class WishHistoryAdmin(admin.ModelAdmin):
    list_display = ('user', 'event', 'status', 'language', 'created_at')
    list_filter = ('status', 'language')
