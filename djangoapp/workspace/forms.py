from django import forms
from .models import Workspace, Team, Task

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
        fields = ['title', 'description', 'team', 'assignee', 'status']
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
        }
        labels = {
            'title': 'Название задачи',
            'description': 'Описание',
            'team': 'Команда',
            'assignee': 'Исполнитель',
            'status': 'Статус',
        }

    def __init__(self, *args, **kwargs):
        self.workspace = kwargs.pop('workspace')
        self.user = kwargs.pop('user')
        self.team_from_get = kwargs.pop('team_from_get', None)
        super().__init__(*args, **kwargs)
        
        # Ограничиваем выбор команд только командами workspace
        self.fields['team'].queryset = Team.objects.filter(workspace=self.workspace)
        self.fields['team'].required = False
        self.fields['team'].empty_label = "Без команды"
        
        # Если команда передана из GET параметра, устанавливаем ее по умолчанию
        if self.team_from_get:
            self.fields['team'].initial = self.team_from_get
        
        # Начальный queryset для исполнителей - все участники workspace
        workspace_members = self.workspace.get_all_members()
        self.fields['assignee'].queryset = workspace_members
        self.fields['assignee'].required = False
        self.fields['assignee'].empty_label = "Не назначено"

    def clean(self):
        cleaned_data = super().clean()
        
        # Временно устанавливаем workspace и reporter для прохождения валидации модели
        if hasattr(self, 'instance'):
            self.instance.workspace = self.workspace
            self.instance.reporter = self.user
        
        team = cleaned_data.get('team')
        assignee = cleaned_data.get('assignee')
        
        # Дополнительная валидация связки команда-исполнитель
        if assignee and team:
            if not team.members.filter(id=assignee.id).exists():
                self.add_error(
                    'assignee', 
                    f'Выбранный исполнитель не состоит в команде {team.name}'
                )
        
        return cleaned_data