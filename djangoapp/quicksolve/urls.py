from django.contrib import admin
from django.urls import include, path
from allauth.account import views

allauth_urls = [
    path('login/', views.LoginView.as_view(), name='account_login'),
    path('logout/', views.LogoutView.as_view(), name='account_logout'),
    path('signup/', views.SignupView.as_view(), name='account_signup'),
    path('email/', views.EmailView.as_view(), name='account_email'),
    path('confirm-email/<str:key>/', views.ConfirmEmailView.as_view(), name='account_confirm_email'),
    path('password/change/', views.PasswordChangeView.as_view(), name='account_change_password'),
    path('password/reset/', views.PasswordResetView.as_view(), name='account_reset_password'),
    path('password/reset/done/', views.PasswordResetDoneView.as_view(), name='account_reset_password_done'),
    path('password/reset/key/<uidb36>/<key>/', views.PasswordResetFromKeyView.as_view(), name='account_reset_password_from_key'),
]

urlpatterns = [
    path('', include("main_page.urls")),
    path('admin/', admin.site.urls),
    path('account/', include(allauth_urls)),
    path('', include('user_profile.urls')),
]