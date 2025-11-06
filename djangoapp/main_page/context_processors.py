from user_profile.models import UserProfile, Notification

def user_profile_and_notifications(request):
    context = {}
    
    if request.user.is_authenticated:
        context['user_profile'] = UserProfile.objects.get(user=request.user)
        notifications = Notification.objects.filter(user=request.user)
        context['notifications'] = notifications
        context['unread_notifications_count'] = notifications.filter(is_read=False).count()
        context['recent_notifications'] = notifications[:5]  # Последние 5 уведомлений
    
    return context