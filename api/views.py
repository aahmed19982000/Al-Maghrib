from rest_framework import generics, permissions, filters
from rest_framework_simplejwt.views import TokenObtainPairView
from news.models import Article, Category
from accounts.models import AuthorProfile
from .serializers import ArticleSerializer, CategorySerializer, AuthorProfileSerializer

class TokenObtainView(TokenObtainPairView):
    """
    Standard JWT token obtain view (login).
    """
    pass

class ArticleAPIView(generics.ListAPIView):
    queryset = Article.objects.filter(status='published').order_by('-published_at')
    serializer_class = ArticleSerializer
    permission_classes = [permissions.AllowAny]

class ArticleDetailAPIView(generics.RetrieveAPIView):
    queryset = Article.objects.filter(status='published')
    serializer_class = ArticleSerializer
    permission_classes = [permissions.AllowAny]

class CategoryAPIView(generics.ListAPIView):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [permissions.AllowAny]

class AuthorAPIView(generics.ListAPIView):
    queryset = AuthorProfile.objects.filter(is_active=True)
    serializer_class = AuthorProfileSerializer
    permission_classes = [permissions.AllowAny]

class AuthorDetailAPIView(generics.RetrieveAPIView):
    queryset = AuthorProfile.objects.filter(is_active=True)
    serializer_class = AuthorProfileSerializer
    permission_classes = [permissions.AllowAny]

class SearchAPIView(generics.ListAPIView):
    serializer_class = ArticleSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        query = self.request.query_params.get('q', '')
        if query:
            return Article.objects.filter(status='published', title__icontains=query) | Article.objects.filter(status='published', body__icontains=query)
        return Article.objects.none()
