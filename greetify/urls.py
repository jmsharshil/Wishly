from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'events', views.EventViewSet, basename='event')
router.register(r'history', views.WishHistoryViewSet, basename='wish-history')

urlpatterns = [
    path('auth/google/url/', views.google_auth_url, name='google-auth-url'),
    path('auth/google/callback/', views.google_auth_callback, name='google-auth-callback'),
    path('auth/google/mobile/', views.google_auth_mobile, name='google-auth-mobile'),
    path('auth/apple/mobile/', views.AppleAuthVerifyView.as_view(), name='apple-auth-mobile'),
    
    path('profile/', views.get_profile, name='profile'),
    path('dashboard/', views.get_dashboard, name='dashboard'),
    
    path('events/sync/', views.sync_google_events, name='sync-events'),
    path('sync/apple/', views.AppleSyncView.as_view(), name='sync-apple'),
    
    path('wishes/generate/', views.generate_ai_wish, name='generate-wish'),
    path('wishes/<int:pk>/edit/', views.edit_wish, name='edit-wish'),
    path('wishes/<int:pk>/mark-sent/', views.mark_wish_sent, name='mark-wish-sent'),
    
    path('', include(router.urls)),
]
