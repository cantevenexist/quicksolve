from django.db import models
from django.contrib.auth import get_user_model
import uuid

User = get_user_model()

class UserProfile(models.Model):
    user = models.OneToOneField(
        User, 
        on_delete=models.CASCADE, 
        related_name='profile'
    )
    about_me = models.TextField(blank=True, null=True)
    unique_code = models.CharField(
        max_length=20, 
        unique=True, 
        blank=True, 
        null=True,
        verbose_name="Unique Code"
    )

    def __str__(self):
        return f'{self.user.username}'

    def save(self, *args, **kwargs):
        """Автоматически генерирует уникальный код при создании профиля"""
        if not self.unique_code:
            code = str(uuid.uuid4())[:12].upper().replace('-', '')
            # Убедимся, что код уникален
            while UserProfile.objects.filter(unique_code=code).exists():
                code = str(uuid.uuid4())[:12].upper().replace('-', '')
            self.unique_code = code
        super().save(*args, **kwargs)


class Notification(models.Model):
    LEVELS = (
        ('info', 'Информация'),
        ('warning', 'Предупреждение'),
        ('error', 'Ошибка'),
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    message = models.TextField()
    level = models.CharField(max_length=10, choices=LEVELS, default='info')
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    related_url = models.URLField(blank=True, null=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.level.upper()}] {self.message[:50]}"