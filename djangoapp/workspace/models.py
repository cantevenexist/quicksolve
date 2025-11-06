from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
import hashlib
import time
import uuid

class Workspace(models.Model):
    DURATION_CHOICES = [
        (None, 'Бессрочно'),
        (3600, '1 час'),
        (14400, '4 часа'),
        (86400, '24 часа'),
        (172800, '48 часов'),
        (259200, '72 часа'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=255, default='Новая рабочая область')
    access_users = models.ManyToManyField(User, blank=True, related_name='accessible_workspaces')
    url_hash = models.CharField(max_length=64, unique=True, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    # Поля для массового приглашения
    mass_invitation_token = models.CharField(max_length=64, unique=True, blank=True, null=True)
    mass_invitation_expiration = models.IntegerField(choices=DURATION_CHOICES, null=True, blank=True)
    mass_invitation_max_uses = models.IntegerField(null=True, blank=True, verbose_name="Максимум использований")
    mass_invitation_current_uses = models.IntegerField(default=0, verbose_name="Текущее количество использований")
    mass_invitation_is_active = models.BooleanField(default=True, verbose_name="Активно")
    mass_invitation_created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.url_hash:
            server_time = str(time.time())
            hash_input = f"{self.name}{server_time}{self.user.username}{uuid.uuid4()}"
            self.url_hash = hashlib.sha256(hash_input.encode('utf-8')).hexdigest()
        
        # Генерируем токен массового приглашения при первом сохранении
        if not self.mass_invitation_token:
            self.mass_invitation_token = self.generate_mass_invitation_token()
        
        super().save(*args, **kwargs)

    def generate_mass_invitation_token(self):
        """Генерирует новый уникальный токен для массового приглашения"""
        return hashlib.sha256(
            f"{self.name}{time.time()}{uuid.uuid4()}".encode('utf-8')
        ).hexdigest()

    def __str__(self):
        return f'{self.name}'

    def get_all_members(self):
        """Возвращает всех участников workspace (владелец + приглашенные)"""
        return User.objects.filter(
            models.Q(id=self.user_id) | 
            models.Q(accessible_workspaces=self)
        ).distinct()
    
    def has_access(self, user):
        """Проверяет, есть ли у пользователя доступ к workspace"""
        return user == self.user or user in self.access_users.all()
    
    def get_mass_invitation_url(self, request):
        """Возвращает полный URL для массового приглашения"""
        if not self.mass_invitation_token:
            return None
        from django.urls import reverse
        return request.build_absolute_uri(
            reverse('workspace:accept_invitation', kwargs={'token': self.mass_invitation_token})
        )
    
    def is_mass_invitation_expired(self):
        """Проверяет, истекло ли время действия массового приглашения"""
        if not self.mass_invitation_expiration:
            return False
        
        from django.utils import timezone
        expiration_date = self.mass_invitation_created_at + timezone.timedelta(seconds=self.mass_invitation_expiration)
        return timezone.now() > expiration_date
    
    def can_mass_invitation_be_used(self):
        """Проверяет, можно ли использовать массовое приглашение"""
        if not self.mass_invitation_is_active:
            return False
        if self.is_mass_invitation_expired():
            return False
        if self.mass_invitation_max_uses and self.mass_invitation_current_uses >= self.mass_invitation_max_uses:
            return False
        return True
    
    def get_mass_invitation_expiration_display(self):
        """Возвращает отображаемое значение срока действия"""
        if not self.mass_invitation_expiration:
            return 'Бессрочно'
        for value, display in self.DURATION_CHOICES:
            if value == self.mass_invitation_expiration:
                return display
        return 'Неизвестно'
    
    def regenerate_mass_invitation_token(self):
        """Генерирует новый токен для массового приглашения"""
        self.mass_invitation_token = self.generate_mass_invitation_token()
        # Проверяем уникальность токена
        while Workspace.objects.filter(mass_invitation_token=self.mass_invitation_token).exists():
            self.mass_invitation_token = self.generate_mass_invitation_token()


class Team(models.Model):
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE)
    name = models.CharField(max_length=255, default='Новая команда')
    members = models.ManyToManyField(User, through='TeamMembership')
    url_hash = models.CharField(max_length=64, unique=True, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.url_hash:
            server_time = str(time.time())
            hash_input = f"{self.name}{server_time}{self.workspace.name}{uuid.uuid4()}"
            self.url_hash = hashlib.sha256(hash_input.encode('utf-8')).hexdigest()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.name}'


class TeamMembership(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    role = models.CharField(max_length=20, default='member')

    class Meta:
        unique_together = ['team', 'user']

    def clean(self):
        """Проверяем, что пользователь является участником workspace"""
        workspace_members = self.team.workspace.get_all_members()
        if self.user not in workspace_members:
            raise ValidationError(
                f"Пользователь {self.user.username} не является участником рабочей области {self.team.workspace.name}"
            )

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.user.username} - {self.team.name}'


class Task(models.Model):
    STATUS_CHOICES = [
        ('backlog', 'Бэклог'),
        ('todo', 'К выполнению'),
        ('in_progress', 'В работе'),
        ('review', 'На проверке'),
        ('done', 'Выполнено'),
    ]
    
    workspace = models.ForeignKey(
        Workspace, 
        on_delete=models.CASCADE,
        verbose_name='Рабочая область'
    )
    team = models.ForeignKey(
        Team, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        verbose_name='Команда'
    )
    title = models.CharField(
        max_length=255,
        verbose_name='Название задачи'
    )
    description = models.TextField(
        blank=True, 
        null=True,
        verbose_name='Описание'
    )
    status = models.CharField(
        max_length=20, 
        choices=STATUS_CHOICES, 
        default='backlog',
        verbose_name='Статус'
    )
    assignee = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='assigned_tasks',
        verbose_name='Исполнитель'
    )
    reporter = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        related_name='reported_tasks',
        verbose_name='Автор'
    )
    url_hash = models.CharField(
        max_length=64, 
        unique=True, 
        blank=True, 
        null=True
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Дата создания'
    )

    class Meta:
        verbose_name = 'Задача'
        verbose_name_plural = 'Задачи'
        ordering = ['-created_at']

    def clean(self):
        """Валидация данных задачи"""
        errors = {}

        # Проверяем, что автор состоит в workspace
        if self.workspace and self.reporter:
            workspace_members = self.workspace.get_all_members()
            if self.reporter not in workspace_members:
                errors['reporter'] = 'Автор задачи должен быть участником рабочей области'

        # Проверяем, что команда принадлежит workspace
        if self.team and self.workspace:
            if self.team.workspace != self.workspace:
                errors['team'] = 'Команда должна принадлежать той же рабочей области'

        # Проверяем, что исполнитель состоит в команде (если команда указана)
        if self.assignee and self.team:
            if not self.team.members.filter(id=self.assignee.id).exists():
                errors['assignee'] = f'Исполнитель не состоит в команде {self.team.name}'

        # Проверяем, что исполнитель состоит в workspace (если команда не указана)
        if self.assignee and not self.team and self.workspace:
            workspace_members = self.workspace.get_all_members()
            if self.assignee not in workspace_members:
                errors['assignee'] = 'Исполнитель должен быть участником рабочей области'

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        # Генерируем URL hash если его нет
        if not self.url_hash:
            server_time = str(time.time())
            hash_input = f"{self.title}{server_time}{self.workspace.name}{uuid.uuid4()}"
            self.url_hash = hashlib.sha256(hash_input.encode('utf-8')).hexdigest()
        
        # Выполняем валидацию
        self.clean()
        super().save(*args, **kwargs)

    def get_available_assignees(self):
        """Возвращает доступных исполнителей для задачи"""
        if self.team:
            # Если есть команда - только участники команды
            return self.team.members.all()
        else:
            # Если команды нет - все участники workspace
            return self.workspace.get_all_members()

    def __str__(self):
        return f'{self.title} (Workspace: {self.workspace.name})'


class IndividualInvitation(models.Model):
    """Модель для точечных приглашений"""
    
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE)
    created_by = models.ForeignKey(
        User, 
        on_delete=models.CASCADE,
        related_name='created_invitations'
    )
    invited_user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='received_invitations'
    )
    invitation_token = models.CharField(max_length=64, unique=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Ожидает'),
            ('accepted', 'Принято'),
            ('expired', 'Истекло'),
        ],
        default='pending'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        # Уникальное ограничение, чтобы нельзя было пригласить одного пользователя дважды
        constraints = [
            models.UniqueConstraint(
                fields=['workspace', 'invited_user'],
                condition=models.Q(status='pending'),
                name='unique_pending_invitation_per_user'
            )
        ]
    
    def save(self, *args, **kwargs):
        if not self.invitation_token:
            self.invitation_token = hashlib.sha256(
                f"{self.workspace.name}{time.time()}{uuid.uuid4()}".encode('utf-8')
            ).hexdigest()
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"Приглашение для {self.invited_user.email} в {self.workspace.name}"