from django.urls import path
from .views import (
    DashboardHomeView, 
    ArticleAdminView, 
    ArticleCreateView, 
    ArticleUpdateView, 
    ArticlePreviewView, 
    ArticleBulkActionView,
    ArticleAutoSaveView,
    CategoryTreeView, 
    CategoryCreateView,
    CategoryUpdateView,
    AuthorStatsView,
    AuthorManagementListView,
    AuthorManagementDetailView,
    AuthorCreateView,
    CommentActionView,
    HomePageSettingsView,
    SiteSettingsView
)

app_name = 'dashboard'

urlpatterns = [
    path('', DashboardHomeView.as_view(), name='home'),
    path('articles/', ArticleAdminView.as_view(), name='articles'),
    path('articles/auto-save/', ArticleAutoSaveView.as_view(), name='article_auto_save'),
    path('articles/create/', ArticleCreateView.as_view(), name='article_create'),
    path('articles/<int:pk>/edit/', ArticleUpdateView.as_view(), name='article_edit'),
    path('articles/<int:pk>/preview/', ArticlePreviewView.as_view(), name='article_preview'),
    path('articles/bulk-action/', ArticleBulkActionView.as_view(), name='article_bulk_action'),
    path('categories/', CategoryTreeView.as_view(), name='categories'),
    path('categories/create/', CategoryCreateView.as_view(), name='category_create'),
    path('categories/<int:pk>/edit/', CategoryUpdateView.as_view(), name='category_edit'),
    path('stats/', AuthorStatsView.as_view(), name='stats'),
    path('settings/home/', HomePageSettingsView.as_view(), name='homepage_settings'),
    path('settings/site/', SiteSettingsView.as_view(), name='site_settings'),
    
    # Comments moderation
    path('comments/<int:pk>/action/', CommentActionView.as_view(), name='comment_action'),
    
    # Author Management (Staff/Admin)
    path('authors/', AuthorManagementListView.as_view(), name='authors_list'),
    path('authors/create/', AuthorCreateView.as_view(), name='author_create'),
    path('authors/<int:pk>/', AuthorManagementDetailView.as_view(), name='author_detail_mgmt'),
]
