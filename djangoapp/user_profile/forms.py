from django import forms
from .models import UserProfile
from allauth.socialaccount.forms import SignupForm
from django.conf import settings
from django.contrib.auth.models import User

class UserProfileForm(forms.ModelForm):
    unique_code = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Ваш уникальный код',
            'readonly': 'readonly'  # Делаем поле только для чтения
        }),
        help_text="Этот код можно использовать только один раз. При обновлении старый код станет недействительным."
    )
    
    class Meta:
        model = UserProfile
        fields = ['about_me', 'unique_code']
        widgets = {
            'about_me': forms.Textarea(attrs={
                'rows': 4,
                'class': 'form-control',
                'placeholder': 'Tell us about yourself...'
            }),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Делаем поле уникального кода недоступным для прямого редактирования
        self.fields['unique_code'].widget.attrs['readonly'] = True
        
class CustomSignupForm(SignupForm):
    username = forms.CharField(label="Username")

    def __init__(self, *args, **kwargs):
        super(CustomSignupForm, self).__init__(*args, **kwargs)

        if not settings.SOCIALACCOUNT_EMAIL_REQUIRED:
            if 'email' in self.fields:
                self.fields['email'].widget = forms.HiddenInput()

    def clean_username(self):
        username = self.cleaned_data.get('username')

        if User.objects.filter(username=username).exists():
            self.add_error('username', "Этот логин уже занят.")
        if username.lower() in settings.ACCOUNT_USERNAME_BLACKLIST:
            self.add_error('username', "Такое имя пользователя не может быть использовано, выберите другое.")
        if len(username) < settings.ACCOUNT_USERNAME_MIN_LENGTH:
            self.add_error('username', "Увеличьте имя пользователя до 4 символов или более.")

        return username

    def clean(self):
        cleaned_data = super().clean()
        return cleaned_data

    def save(self, request):
        user = super().save(request)
        user.username = self.cleaned_data['username']

        if not settings.SOCIALACCOUNT_EMAIL_REQUIRED:
            user.email = ''

        user.save()

        return user