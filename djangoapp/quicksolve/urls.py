from django.contrib import admin
from django.urls import include, path
from allauth.account import views

allauth_urls = [
    path("signup/", views.signup, name="account_signup"),
    path("login/", views.login, name="account_login"),
    path("logout/", views.logout, name="account_logout"),
    path("password/change/", views.password_change, name="account_change_password"),
    path("password/set/", views.password_set, name="account_set_password"),
    path("inactive/", views.account_inactive, name="account_inactive"),
    
    # E-mail
    path("email/", views.email, name="account_email"),
    path("confirm-email/", views.email_verification_sent, name="account_email_verification_sent"),
    path("confirm-email/<key>/", views.confirm_email, name="account_confirm_email"),
    
    # Password reset
    path("password/reset/", views.password_reset, name="account_reset_password"),
    path("password/reset/done/", views.password_reset_done, name="account_reset_password_done"),
    path("password/reset/key/<uidb36>/<key>/", views.password_reset_from_key, name="account_reset_password_from_key"),
    path("password/reset/key/done/", views.password_reset_from_key_done, name="account_reset_password_from_key_done"),
]

urlpatterns = [
    path('', include('main_page.urls')),
    path('admin/', admin.site.urls),
    path('account/', include(allauth_urls)),
    path('', include('user_profile.urls')),
    path('workspace/', include('workspace.urls')),
]