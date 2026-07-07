from django.urls import path
from . import views_ai

app_name = 'news_ai'

urlpatterns = [
    path('', views_ai.DashboardIndexView.as_view(), name='index'),
    path('settings/', views_ai.SettingsUpdateView.as_view(), name='settings'),
    path('sources/', views_ai.SourceListView.as_view(), name='sources'),
    path('sources/add/', views_ai.SourceCreateView.as_view(), name='source_add'),
    path('sources/<int:pk>/edit/', views_ai.SourceUpdateView.as_view(), name='source_edit'),
    path('sources/<int:pk>/delete/', views_ai.SourceDeleteView.as_view(), name='source_delete'),
    path('logs/', views_ai.ImportLogListView.as_view(), name='logs'),
    path('trigger/', views_ai.TriggerScraperView.as_view(), name='trigger'),
    # WordPress Sites
    path('wp-sites/', views_ai.WordPressSiteListView.as_view(), name='wp_sites'),
    path('wp-sites/add/', views_ai.WordPressSiteCreateView.as_view(), name='wp_site_add'),
    path('wp-sites/<int:pk>/edit/', views_ai.WordPressSiteUpdateView.as_view(), name='wp_site_edit'),
    path('wp-sites/<int:pk>/delete/', views_ai.WordPressSiteDeleteView.as_view(), name='wp_site_delete'),
]
