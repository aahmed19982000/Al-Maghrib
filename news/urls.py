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
    path('category/<slug:slug>/', cache_page(60 * 15)(CategoryListView.as_view()), name='category_list'),
    path('authors/<int:pk>/', AuthorDetailView.as_view(), name='author_detail'),
    path('<slug:slug>/', ArticleDetailView.as_view(), name='article_detail'),
    path('<slug:slug>/comment/', CommentSubmitView.as_view(), name='submit_comment'),
    path('<slug:slug>/like/', ArticleLikeToggleView.as_view(), name='like_article'),
    path('<slug:slug>/bookmark/', ArticleBookmarkToggleView.as_view(), name='bookmark_article'),
]
