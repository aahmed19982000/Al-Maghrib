from django.urls import path
from django.contrib.auth import views as auth_views
from .views import TeamListView, ProfileEditView, custom_logout

app_name = 'accounts'

urlpatterns = [
    path('team/', TeamListView.as_view(), name='team_list'),
    path('profile/edit/', ProfileEditView.as_view(), name='profile_edit'),
    path('login/', auth_views.LoginView.as_view(template_name='accounts/login.html'), name='login'),
    path('logout/', custom_logout, name='logout'),
]
