from django.urls import path
from . import views

app_name = 'workspace'

urlpatterns = [
    # === WORKSPACE ===
    path('', views.WorkspaceIndexView.as_view(), name='workspace_index'),
    path('create/', views.WorkspaceCreateView.as_view(), name='workspace_create'),
    path('<str:workspace_url_hash>/', views.WorkspaceDetailView.as_view(), name='workspace_detail'),
    
    # === TEAMS ===
    path('<str:workspace_url_hash>/team/create/', views.TeamCreateView.as_view(), name='team_create'),
    path('<str:workspace_url_hash>/team/<str:team_url_hash>/', views.TeamDetailView.as_view(), name='team_detail'),
    
    # === TASKS ===
    path('<str:workspace_url_hash>/tasks/', views.TaskListView.as_view(), name='task_list'),
    path('<str:workspace_url_hash>/task/create/', views.TaskCreateView.as_view(), name='task_create'),
    path('<str:workspace_url_hash>/task/<str:task_url_hash>/', views.TaskDetailView.as_view(), name='task_detail'),
]