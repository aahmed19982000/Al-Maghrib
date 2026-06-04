from django.urls import path
from django.views.decorators.cache import cache_page
from .views import (
    ArticleListView, 
    ArticleDetailView, 
    CategoryListView, 
    BreakingNewsView, 
    AuthorDetailView, 
    CommentSubmitView,
    ArticleLikeToggleView,
    ArticleBookmarkToggleView
)

app_name = 'news'

urlpatterns = [
    path('', ArticleListView.as_view(), name='article_list'),
    path('breaking/', BreakingNewsView.as_view(), name='breaking_news'),
    path('category/<str:slug>/', CategoryListView.as_view(), name='category_list'),
    path('authors/<int:pk>/', AuthorDetailView.as_view(), name='author_detail'),
    path('<str:slug>/', ArticleDetailView.as_view(), name='article_detail'),
    path('<str:slug>/comment/', CommentSubmitView.as_view(), name='submit_comment'),
    path('<str:slug>/like/', ArticleLikeToggleView.as_view(), name='like_article'),
    path('<str:slug>/bookmark/', ArticleBookmarkToggleView.as_view(), name='bookmark_article'),
]
