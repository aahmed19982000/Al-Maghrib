from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .views import (
    TokenObtainView,
    ArticleAPIView,
    ArticleDetailAPIView,
    CategoryAPIView,
    AuthorAPIView,
    AuthorDetailAPIView,
    SearchAPIView
)

app_name = 'api'

urlpatterns = [
    path('token/', TokenObtainView.as_view(), name='token_obtain_pair'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('articles/', ArticleAPIView.as_view(), name='article_list'),
    path('articles/<int:pk>/', ArticleDetailAPIView.as_view(), name='article_detail'),
    path('categories/', CategoryAPIView.as_view(), name='category_list'),
    path('authors/', AuthorAPIView.as_view(), name='author_list'),
    path('authors/<int:pk>/', AuthorDetailAPIView.as_view(), name='author_detail'),
    path('search/', SearchAPIView.as_view(), name='search'),
]
