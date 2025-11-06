from django.urls import path
from . import views

urlpatterns = [
    path('profile/', views.MyProfileView.as_view(), name='profile_self'),
    path('profile/<str:username>/', views.ProfileView.as_view(), name='profile'),
    path('account/settings/edit_profile/', views.ProfileEditView.as_view(), name='profile_edit'),
    path('account/regenerate_code/', views.RegenerateUniqueCodeView.as_view(), name='regenerate_code'),
    path('notifications/<int:notification_id>/', views.NotificationDetailView.as_view(), name='notification_detail'),
    path('notifications/all/', views.AllNotificationsView.as_view(), name='all_notifications'),
    path('notifications/<int:notification_id>/mark-read/', views.MarkNotificationReadView.as_view(), name='mark_notification_read'),
]