from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils import timezone
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
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name='Владелец')
    name = models.CharField(max_length=255, default='Новая рабочая область', verbose_name='Название')
    description = models.CharField(max_length=255, blank=True, null=True)
    members = models.ManyToManyField(User, through='WorkspaceMembership', related_name='workspaces')
    url_hash = models.CharField(max_length=64, unique=True, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Дата создания')
    
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
        
        # После создания workspace добавляем владельца как участника с ролью owner
        if not WorkspaceMembership.objects.filter(workspace=self, user=self.user).exists():
            WorkspaceMembership.objects.create(
                workspace=self, 
                user=self.user, 
                role='owner'
            )

    def generate_mass_invitation_token(self):
        """Генерирует новый уникальный токен для массового приглашения"""
        return hashlib.sha256(
            f"{self.name}{time.time()}{uuid.uuid4()}".encode('utf-8')
        ).hexdigest()

    def __str__(self):
        return f'{self.name}'

    def get_all_members(self):
        """Возвращает всех участников workspace"""
        return User.objects.filter(workspacemembership__workspace=self).distinct()
    
    def has_access(self, user):
        """Проверяет, есть ли у пользователя доступ к workspace"""
        return WorkspaceMembership.objects.filter(workspace=self, user=user).exists()
    
    def get_user_role(self, user):
        """Возвращает роль пользователя в workspace"""
        try:
            membership = WorkspaceMembership.objects.get(workspace=self, user=user)
            return membership.role
        except WorkspaceMembership.DoesNotExist:
            return None
    
    def is_owner(self, user):
        """Проверяет, является ли пользователь владельцем workspace"""
        return WorkspaceMembership.objects.filter(workspace=self, user=user, role='owner').exists()
    
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


class WorkspaceMembership(models.Model):
    ROLE_CHOICES = [
        ('owner', 'Владелец'),
        ('admin', 'Администратор'),
        ('member', 'Участник'),
    ]
    
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='member')

    class Meta:
        unique_together = ['workspace', 'user']
        verbose_name = 'Участник рабочей области'
        verbose_name_plural = 'Участники рабочих областей'

    def clean(self):
        """Валидация данных участника workspace"""
        # Проверяем, что может быть только один владелец
        if self.role == 'owner':
            existing_owner = WorkspaceMembership.objects.filter(
                workspace=self.workspace, 
                role='owner'
            ).exclude(id=self.id)
            if existing_owner.exists():
                raise ValidationError('В рабочей области может быть только один владелец')

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.user.username} - {self.workspace.name} ({self.get_role_display()})'


class WorkspaceRoleAccess(models.Model):
    """
    Модель для управления правами доступа в рабочей области
    """
    workspace = models.OneToOneField(Workspace, on_delete=models.CASCADE, related_name='role_access')
    
    # Права управления доступом
    can_manage_access = models.JSONField(
        default=list,
        help_text="Роли, которые могут управлять доступом к workspace"
    )
    
    # Права изменения workspace
    can_edit_workspace = models.JSONField(
        default=list,
        help_text="Роли, которые могут изменять workspace"
    )
    
    # Права создания команд
    can_create_teams = models.JSONField(
        default=list,
        help_text="Роли, которые могут создавать команды"
    )
    
    # Права создания задач
    can_create_tasks = models.JSONField(
        default=list,
        help_text="Роли, которые могут создавать задачи"
    )
    
    # Права редактирования задач
    can_edit_tasks = models.JSONField(
        default=list,
        help_text="Роли, которые могут редактировать задачи"
    )
    
    # Права удаления задач
    can_delete_tasks = models.JSONField(
        default=list,
        help_text="Роли, которые могут удалять задачи"
    )
    
    # Права приглашения пользователей
    can_invite_users = models.JSONField(
        default=list,
        help_text="Роли, которые могут приглашать новых пользователей"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Настройка прав рабочей области'
        verbose_name_plural = 'Настройки прав рабочих областей'

    def save(self, *args, **kwargs):
        # Устанавливаем значения по умолчанию при первом создании
        if not self.pk:
            self.set_default_permissions()
        super().save(*args, **kwargs)

    def set_default_permissions(self):
        """Устанавливает права доступа по умолчанию"""
        self.can_manage_access = ['owner', 'admin']
        self.can_edit_workspace = ['owner', 'admin', 'member']
        self.can_create_teams = ['owner', 'admin', 'member']
        self.can_create_tasks = ['owner', 'admin', 'member']
        self.can_edit_tasks = ['owner', 'admin', 'member']
        self.can_delete_tasks = ['owner', 'admin', 'member']
        self.can_invite_users = ['owner', 'admin', 'member']

    def has_permission(self, user, permission_type):
        """Проверяет, имеет ли пользователь указанное право"""
        # Получаем роль пользователя в workspace
        user_role = self.workspace.get_user_role(user)
        if not user_role:
            return False
        
        # Владелец workspace имеет все права
        if user_role == 'owner':
            return True
        
        # Проверяем права для конкретного действия
        permission_field = getattr(self, permission_type, [])
        return user_role in permission_field

    def __str__(self):
        return f'Права доступа для {self.workspace.name}'


class Team(models.Model):
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE)
    name = models.CharField(max_length=255, default='Новая команда')
    description = models.CharField(max_length=255, blank=True, null=True)
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

    def clean(self):
        """Проверяем, что все участники команды являются участниками workspace"""
        if self.pk:
            team_members = self.members.all()
            workspace_members = self.workspace.get_all_members()
            for member in team_members:
                if member not in workspace_members:
                    raise ValidationError(
                        f"Участник {member.username} не является участником рабочей области"
                    )


class TeamMembership(models.Model):
    ROLE_CHOICES = [
        ('leader', 'Лидер'),
        ('admin', 'Администратор'),
        ('member', 'Участник'),
    ]
    
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='member')

    class Meta:
        unique_together = ['team', 'user']
        verbose_name = 'Участник команды'
        verbose_name_plural = 'Участники команды'

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
        return f'{self.user.username} - {self.team.name} ({self.get_role_display()})'


class TeamRoleAccess(models.Model):
    """
    Модель для управления правами доступа в команде
    """
    VISIBILITY_CHOICES = [
        ('private', 'Только для участников команды'),
        ('workspace', 'Для всех участников workspace'),
    ]
    
    team = models.OneToOneField(Team, on_delete=models.CASCADE, related_name='role_access')
    
    # Права управления доступом
    can_manage_access = models.JSONField(
        default=list,
        help_text="Роли, которые могут управлять доступом к команде"
    )
    
    # Права редактирования команды
    can_edit_team = models.JSONField(
        default=list,
        help_text="Роли, которые могут редактировать команду"
    )
    
    # Права приглашения пользователей
    can_invite_users = models.JSONField(
        default=list,
        help_text="Роли, которые могут приглашать пользователей в команду"
    )
    
    # Права для задач
    can_create_tasks = models.JSONField(
        default=list,
        help_text="Роли, которые могут создавать задачи в команде"
    )
    
    can_edit_tasks = models.JSONField(
        default=list,
        help_text="Роли, которые могут редактировать задачи в команде"
    )
    
    can_delete_tasks = models.JSONField(
        default=list,
        help_text="Роли, которые могут удалять задачи в команде"
    )
    
    # Видимость команды
    visibility = models.CharField(
        max_length=20,
        choices=VISIBILITY_CHOICES,
        default='private',
        help_text="Видимость команды для пользователей, которые не состоят в команде"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Настройка прав команды'
        verbose_name_plural = 'Настройки прав команд'

    def save(self, *args, **kwargs):
        # Устанавливаем значения по умолчанию при первом создании
        if not self.pk:
            self.set_default_permissions()
        super().save(*args, **kwargs)

    def set_default_permissions(self):
        """Устанавливает права доступа по умолчанию"""
        self.can_manage_access = ['leader', 'admin', 'member']
        self.can_edit_team = ['leader', 'admin', 'member']
        self.can_invite_users = ['leader', 'admin', 'member']
        self.can_create_tasks = ['leader', 'admin', 'member']
        self.can_edit_tasks = ['leader', 'admin', 'member']
        self.can_delete_tasks = ['leader', 'admin', 'member']
        self.visibility = 'private'

    def has_permission(self, user, permission_type):
        """Проверяет, имеет ли пользователь указанное право в команде"""
        # Проверяем, является ли пользователь владельцем или администратором workspace
        workspace_role = self.team.workspace.get_user_role(user)
        if workspace_role == 'owner':
            return True
        
        # Получаем роль пользователя в команде
        try:
            team_membership = TeamMembership.objects.get(team=self.team, user=user)
            user_role = team_membership.role
        except TeamMembership.DoesNotExist:
            return False
        
        # Лидер команды имеет все права администратора
        if user_role == 'leader':
            return True
        
        # Проверяем права для конкретного действия
        permission_field = getattr(self, permission_type, [])
        return user_role in permission_field

    def is_team_visible_to_user(self, user):
        """Проверяет, видна ли команда пользователю"""
        # Владельцы и администраторы workspace всегда видят все команды
        workspace_role = self.team.workspace.get_user_role(user)
        if workspace_role in ['owner', 'admin']:
            return True
        
        # Участники команды всегда видят свою команду
        if TeamMembership.objects.filter(team=self.team, user=user).exists():
            return True
        
        # Проверяем настройки видимости
        if self.visibility == 'workspace':
            # Команда видна всем участникам workspace
            return self.team.workspace.has_access(user)
        
        # По умолчанию команда приватная
        return False

    def __str__(self):
        return f'Права доступа для команды {self.team.name}'


class Task(models.Model):
    STATUS_CHOICES = [
        ('backlog', 'Бэклог'),
        ('todo', 'К выполнению'),
        ('in_progress', 'В работе'),
        ('review', 'На проверке'),
        ('done', 'Выполнено'),
    ]
    
    PRIORITY_CHOICES = [
        ('none', 'Не указан'),
        ('low', 'Низкий'),
        ('medium', 'Средний'),
        ('high', 'Высокий'),
        ('very_high', 'Очень высокий'),
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
    priority = models.CharField(
        max_length=20,
        choices=PRIORITY_CHOICES,
        default='none',
        verbose_name='Приоритет'
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
        on_delete=models.SET_NULL,
        null=True, 
        blank=True,
        related_name='reported_tasks',
        verbose_name='Автор'
    )
    
    deadline = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Дедлайн'
    )
    visible = models.BooleanField(
        default=True,
        verbose_name='Видимый'
    )
    
    # Права редактирования для обычных редакторов (не создателя, не владельца, не лидера)
    can_edit_content = models.BooleanField(
        default=True,
        verbose_name='Редакторы могут изменять содержание'
    )
    can_edit_team = models.BooleanField(
        default=True,
        verbose_name='Редакторы могут изменять команду'
    )
    can_edit_assignee = models.BooleanField(
        default=True,
        verbose_name='Редакторы могут изменять исполнителя'
    )
    can_edit_visibility = models.BooleanField(
        default=True,
        verbose_name='Редакторы могут изменять видимость'
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
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='Дата обновления'
    )
    updated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='updated_tasks',
        verbose_name='Кем обновлено'
    )

    class Meta:
        verbose_name = 'Задача'
        verbose_name_plural = 'Задачи'
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        # Генерируем URL hash если его нет
        if not self.url_hash:
            server_time = str(time.time())
            hash_input = f"{self.title}{server_time}{self.workspace.name}{uuid.uuid4()}"
            self.url_hash = hashlib.sha256(hash_input.encode('utf-8')).hexdigest()
        
        # Если это создание новой задачи, устанавливаем updated_by
        if not self.pk and self.reporter:
            self.updated_by = self.reporter
        
        # Выполняем валидацию
        self.clean()
        super().save(*args, **kwargs)

    def clean(self):
        """Валидация данных задачи"""
        errors = {}

        # Проверяем, что автор состоит в workspace
        if self.workspace and self.reporter:
            if not self.workspace.has_access(self.reporter):
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
            if not self.workspace.has_access(self.assignee):
                errors['assignee'] = 'Исполнитель должен быть участником рабочей области'

        if errors:
            raise ValidationError(errors)

    def get_available_assignees(self):
        """Возвращает доступных исполнителей для задачи"""
        if self.team:
            # Если есть команда - только участники команды
            return self.team.members.all()
        else:
            # Если команды нет - все участники workspace
            return self.workspace.get_all_members()

    def get_editors(self):
        """
        Возвращает список пользователей, которые могут редактировать эту задачу
        согласно правилам:
        1. Создатель задачи (ВСЕГДА)
        2. Владелец рабочей области (ВСЕГДА)
        3. Лидер команды (если задача назначена на команду) (ВСЕГДА)
        4. Исполнитель задачи (если назначен)
        5. Пользователи с правом редактирования задач в workspace/team
        """
        editors = set()
        
        # 1. Создатель задачи (ВСЕГДА)
        editors.add(self.reporter)
        
        # 2. Владелец рабочей области (ВСЕГДА)
        workspace_owner = WorkspaceMembership.objects.filter(
            workspace=self.workspace,
            role='owner'
        ).first()
        if workspace_owner:
            editors.add(workspace_owner.user)
        
        # 3. Лидер команды (если задача назначена на команду) (ВСЕГДА)
        if self.team:
            team_leader = TeamMembership.objects.filter(
                team=self.team,
                role='leader'
            ).first()
            if team_leader:
                editors.add(team_leader.user)
        
        # 4. Исполнитель задачи (если назначен)
        if self.assignee:
            editors.add(self.assignee)
        
        # 5. Пользователи с правом редактирования задач в workspace/team
        if self.team:
            # Для задач в команде - проверяем права в команде
            team_access, _ = TeamRoleAccess.objects.get_or_create(team=self.team)
            team_members = TeamMembership.objects.filter(team=self.team)
            for member in team_members:
                if team_access.has_permission(member.user, 'can_edit_tasks'):
                    editors.add(member.user)
        else:
            # Для задач без команды - проверяем права в workspace
            workspace_access, _ = WorkspaceRoleAccess.objects.get_or_create(workspace=self.workspace)
            workspace_members = WorkspaceMembership.objects.filter(workspace=self.workspace)
            for member in workspace_members:
                if workspace_access.has_permission(member.user, 'can_edit_tasks'):
                    editors.add(member.user)
        
        return list(editors)

    def is_special_editor(self, user):
        """
        Проверяет, является ли пользователь особым редактором:
        - Создатель
        - Владелец workspace  
        - Лидер команды (если задача в команде)
        Эти пользователи имеют ВСЕ права ВСЕГДА
        """
        # 1. Создатель задачи (ВСЕГДА)
        if user == self.reporter:
            return True
        
        # 2. Владелец рабочей области (ВСЕГДА)
        workspace_owner_membership = WorkspaceMembership.objects.filter(
            workspace=self.workspace,
            user=user,
            role='owner'
        ).first()
        if workspace_owner_membership:
            return True
        
        # 3. Лидер команды (если задача назначена на команду) (ВСЕГДА)
        if self.team:
            team_leader_membership = TeamMembership.objects.filter(
                team=self.team,
                user=user,
                role='leader'
            ).first()
            if team_leader_membership:
                return True
        
        return False

    def can_user_edit(self, user):
        """Проверяет, может ли пользователь редактировать эту задачу"""
        # Специальные редакторы могут редактировать всегда
        if self.is_special_editor(user):
            return True
        
        # Исполнитель задачи может редактировать
        if self.assignee and user == self.assignee:
            return True
        
        # Обычные редакторы из команды/workspace
        if self.team:
            # Для задач в команде
            team_access, _ = TeamRoleAccess.objects.get_or_create(team=self.team)
            try:
                team_membership = TeamMembership.objects.get(team=self.team, user=user)
                return team_access.has_permission(user, 'can_edit_tasks')
            except TeamMembership.DoesNotExist:
                return False
        else:
            # Для задач без команды
            workspace_access, _ = WorkspaceRoleAccess.objects.get_or_create(workspace=self.workspace)
            try:
                workspace_membership = WorkspaceMembership.objects.get(workspace=self.workspace, user=user)
                return workspace_access.has_permission(user, 'can_edit_tasks')
            except WorkspaceMembership.DoesNotExist:
                return False

    def can_user_edit_content(self, user):
        """Проверяет, может ли пользователь редактировать содержание задачи"""
        if not self.can_user_edit(user):
            return False
        
        # Специальные редакторы могут редактировать всегда
        if self.is_special_editor(user):
            return True
        
        # Для обычных редакторов - проверяем настройки задачи
        return self.can_edit_content

    def can_user_edit_team(self, user):
        """Проверяет, может ли пользователь изменять команду задачи"""
        if not self.can_user_edit(user):
            return False
        
        # Специальные редакторы могут редактировать всегда
        if self.is_special_editor(user):
            return True
        
        # Для обычных редакторов - проверяем настройки задачи
        return self.can_edit_team

    def can_user_edit_assignee(self, user):
        """Проверяет, может ли пользователь изменять исполнителя задачи"""
        if not self.can_user_edit(user):
            return False
        
        # Специальные редакторы могут редактировать всегда
        if self.is_special_editor(user):
            return True
        
        # Для обычных редакторов - проверяем настройки задачи
        return self.can_edit_assignee

    def can_user_edit_visibility(self, user):
        """Проверяет, может ли пользователь изменять видимость задачи"""
        if not self.can_user_edit(user):
            return False
        
        # Специальные редакторы могут редактировать всегда
        if self.is_special_editor(user):
            return True
        
        # Для обычных редакторов - проверяем настройки задачи
        return self.can_edit_visibility

    def is_visible_to_user(self, user):
        """
        Проверяет, видна ли задача пользователю
        Согласно правилам:
        1. Создатель задачи всегда видит ее
        2. Исполнитель задачи всегда видит ее
        3. Редакторы задачи всегда видят ее
        4. Лидер команды видит все задачи в команде
        5. Владелец workspace видит все задачи
        6. Для остальных: зависит от настройки visible
        """
        # 1. Создатель всегда видит
        if user == self.reporter:
            return True
        
        # 2. Исполнитель всегда видит
        if self.assignee and user == self.assignee:
            return True
        
        # 3. Редакторы всегда видят
        if self.can_user_edit(user):
            return True
        
        # 4. Лидер команды видит все задачи в команде
        if self.team:
            try:
                membership = TeamMembership.objects.get(team=self.team, user=user)
                if membership.role == 'leader':
                    return True
            except TeamMembership.DoesNotExist:
                pass
        
        # 5. Владелец workspace видит все задачи
        workspace_membership = WorkspaceMembership.objects.filter(
            workspace=self.workspace,
            user=user,
            role='owner'
        ).first()
        if workspace_membership:
            return True
        
        # 6. Для остальных - зависит от настройки visible
        return self.visible

    def can_user_change_permissions(self, user):
        """
        Проверяет, может ли пользователь изменять права доступа к задаче
        Только: создатель, владелец workspace, лидер команды (если есть)
        """
        return self.is_special_editor(user)

    def __str__(self):
        return f'{self.title} (Workspace: {self.workspace.name})'


class IndividualInvitation(models.Model):
    """Модель для точечных приглашений"""
    
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE)
    created_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
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