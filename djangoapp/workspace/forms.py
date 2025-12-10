from django import forms
from .models import Workspace, Team, Task, WorkspaceRoleAccess, TeamRoleAccess

class WorkspaceCreateForm(forms.ModelForm):
    class Meta:
        model = Workspace
        fields = ['name']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Введите название рабочей области'
            })
        }
        labels = {
            'name': 'Название рабочей области'
        }


class TeamCreateForm(forms.ModelForm):
    class Meta:
        model = Team
        fields = ['name']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Введите название команды'
            })
        }
        labels = {
            'name': 'Название команды'
        }


class TaskCreateForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = [
            'title', 'description', 'team', 'assignee', 'status', 
            'priority', 'deadline', 'visible',
            'can_edit_content', 'can_edit_team', 'can_edit_assignee', 'can_edit_visibility'
        ]
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Введите название задачи'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'placeholder': 'Опишите детали задачи...',
                'rows': 4
            }),
            'team': forms.Select(attrs={
                'class': 'form-control',
                'id': 'team-select'
            }),
            'assignee': forms.Select(attrs={
                'class': 'form-control',
                'id': 'assignee-select'
            }),
            'status': forms.Select(attrs={
                'class': 'form-control'
            }),
            'priority': forms.Select(attrs={
                'class': 'form-control'
            }),
            'deadline': forms.DateTimeInput(attrs={
                'class': 'form-control',
                'type': 'datetime-local'
            }),
            'visible': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'can_edit_content': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'can_edit_team': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'can_edit_assignee': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'can_edit_visibility': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
        }
        labels = {
            'title': 'Название задачи',
            'description': 'Описание',
            'team': 'Команда',
            'assignee': 'Исполнитель',
            'status': 'Статус',
            'priority': 'Приоритет',
            'deadline': 'Дедлайн',
            'visible': 'Видимая задача',
            'can_edit_content': 'Редакторы могут изменять содержание',
            'can_edit_team': 'Редакторы могут изменять команду',
            'can_edit_assignee': 'Редакторы могут изменять исполнителя',
            'can_edit_visibility': 'Редакторы могут изменять видимость',
        }

    def __init__(self, *args, **kwargs):
        self.workspace = kwargs.pop('workspace')
        self.user = kwargs.pop('user')
        self.team_from_get = kwargs.pop('team_from_get', None)
        self.can_create_in_workspace = kwargs.pop('can_create_in_workspace', False)
        self.user_teams_with_task_create_rights = kwargs.pop('user_teams_with_task_create_rights', [])
        
        super().__init__(*args, **kwargs)
        
        # Фильтрация команд в зависимости от прав пользователя
        self.filter_team_choices()
        
        # Если команда передана из GET параметра, устанавливаем ее по умолчанию
        if self.team_from_get:
            self.fields['team'].initial = self.team_from_get
        
        # Динамически обновляем список исполнителей в зависимости от выбранной команды
        self.fields['assignee'].queryset = self.workspace.get_all_members()
        self.fields['assignee'].required = False
        self.fields['assignee'].empty_label = "Не назначено"
        
        # Устанавливаем значения по умолчанию
        self.fields['visible'].initial = True
        self.fields['can_edit_content'].initial = True
        self.fields['can_edit_team'].initial = True
        self.fields['can_edit_assignee'].initial = True
        self.fields['can_edit_visibility'].initial = True

    def filter_team_choices(self):
        """Фильтрует список команд в зависимости от прав пользователя"""
        if not self.can_create_in_workspace and not self.user_teams_with_task_create_rights:
            # У пользователя нет прав нигде
            self.fields['team'].queryset = Team.objects.none()
            self.fields['team'].empty_label = "Нет доступных команд"
        elif not self.can_create_in_workspace and self.user_teams_with_task_create_rights:
            # Может создавать только в командах с правами
            self.fields['team'].queryset = Team.objects.filter(
                id__in=[team.id for team in self.user_teams_with_task_create_rights]
            )
            self.fields['team'].empty_label = "Выберите команду"
        elif self.can_create_in_workspace and not self.user_teams_with_task_create_rights:
            # Может создавать только без команды
            self.fields['team'].queryset = Team.objects.none()
            self.fields['team'].empty_label = "Без команды"
        else:
            # Может создавать и в workspace, и в командах с правами
            all_available_teams = list(self.user_teams_with_task_create_rights)
            self.fields['team'].queryset = Team.objects.filter(
                id__in=[team.id for team in all_available_teams]
            )
            self.fields['team'].empty_label = "Без команды"

    def clean(self):
        cleaned_data = super().clean()
        
        # Временно устанавливаем workspace и reporter для прохождения валидации модели
        if hasattr(self, 'instance'):
            self.instance.workspace = self.workspace
            self.instance.reporter = self.user
        
        team = cleaned_data.get('team')
        assignee = cleaned_data.get('assignee')
        
        # Проверка прав для создания задачи в выбранной команде
        if team:
            team_access, _ = TeamRoleAccess.objects.get_or_create(team=team)
            if not team_access.has_permission(self.user, 'can_create_tasks'):
                self.add_error(
                    'team',
                    'У вас нет прав для создания задач в этой команде'
                )
        else:
            # Проверка прав для создания задачи без команды (в workspace)
            workspace_access, _ = WorkspaceRoleAccess.objects.get_or_create(workspace=self.workspace)
            if not workspace_access.has_permission(self.user, 'can_create_tasks'):
                self.add_error(
                    None,
                    'У вас нет прав для создания задач без команды'
                )
        
        # Дополнительная валидация связки команда-исполнитель
        if assignee and team:
            if not team.members.filter(id=assignee.id).exists():
                self.add_error(
                    'assignee', 
                    f'Выбранный исполнитель не состоит в команде {team.name}'
                )
        
        return cleaned_data


class MassInvitationForm(forms.Form):
    """Форма для массового приглашения"""
    
    expiration_time = forms.ChoiceField(
        choices=Workspace.DURATION_CHOICES,
        required=False,
        widget=forms.Select(attrs={
            'class': 'form-control',
            'id': 'expiration-time'
        }),
        label='Срок действия'
    )
    
    max_uses = forms.IntegerField(
        required=False,
        min_value=1,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Оставьте пустым для безграничного использования',
            'min': 1
        }),
        label='Максимум использований'
    )


class IndividualInvitationForm(forms.Form):
    """Форма для точечного приглашения"""
    
    identifiers = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Введите почты или уникальные коды через пробел',
            'id': 'identifiers-input'
        }),
        label='Почты или коды пользователей'
    )