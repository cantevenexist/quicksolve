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

    # === INVITATIONS ===
    path('<str:workspace_url_hash>/invitations/mass/create/', views.CreateMassInvitationView.as_view(), name='create_mass_invitation'),
    path('<str:workspace_url_hash>/invitations/individual/create/', views.CreateIndividualInvitationsView.as_view(), name='create_individual_invitations'),
    path('<str:workspace_url_hash>/invitations/toggle-all/', views.ToggleAllInvitationsView.as_view(), name='toggle_all_invitations'),
    path('invitations/accept/<str:token>/', views.AcceptInvitationView.as_view(), name='accept_invitation'),
    path('<str:workspace_url_hash>/team/<str:team_url_hash>/invite-members/', views.TeamInviteMemberView.as_view(), name='team_invite_members'),
    
    # === KICK ===
    path('<str:workspace_url_hash>/kick-members/', views.WorkspaceKickMemberView.as_view(), name='workspace_kick_members'),
    path('<str:workspace_url_hash>/team/<str:team_url_hash>/kick-members/', views.TeamKickMemberView.as_view(), name='team_kick_members'),
]