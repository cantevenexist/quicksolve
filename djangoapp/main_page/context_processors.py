from user_profile.models import UserProfile


def user_profile(request):
    user_profile = None

    if request.user.is_authenticated:
        user_profile = UserProfile.objects.get(user=request.user)

    return {'user_profile': user_profile}