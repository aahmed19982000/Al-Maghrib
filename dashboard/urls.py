from django.urls import path
from .views import (
    DashboardHomeView, 
    ArticleAdminView, 
    ArticleCreateView, 
    ArticleUpdateView, 
    ArticlePreviewView, 
    ArticleBulkActionView,
    CategoryTreeView, 
    AuthorStatsView,
    AuthorManagementListView,
    AuthorManagementDetailView,
    CommentActionView
)

app_name = 'dashboard'

urlpatterns = [
    path('', DashboardHomeView.as_view(), name='home'),
    path('articles/', ArticleAdminView.as_view(), name='articles'),
    path('articles/create/', ArticleCreateView.as_view(), name='article_create'),
    path('articles/<int:pk>/edit/', ArticleUpdateView.as_view(), name='article_edit'),
    path('articles/<int:pk>/preview/', ArticlePreviewView.as_view(), name='article_preview'),
    path('articles/bulk-action/', ArticleBulkActionView.as_view(), name='article_bulk_action'),
    path('categories/', CategoryTreeView.as_view(), name='categories'),
    path('stats/', AuthorStatsView.as_view(), name='stats'),
    
    # Comments moderation
    path('comments/<int:pk>/action/', CommentActionView.as_view(), name='comment_action'),
    
    # Author Management (Staff/Admin)
    path('authors/', AuthorManagementListView.as_view(), name='authors_list'),
    path('authors/<int:pk>/', AuthorManagementDetailView.as_view(), name='author_detail_mgmt'),
]
