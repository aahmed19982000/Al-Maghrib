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


from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions, status
from django.contrib.auth.models import User
from news.models import AISettings, Category

class AISettingsAPIView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def get(self, request, *args, **kwargs):
        settings_obj = AISettings.get_settings()
        categories_data = [{"id": cat.id, "name": cat.name} for cat in Category.objects.filter(is_active=True)]
        authors_data = [{"id": u.id, "username": u.username, "name": u.get_full_name()} for u in User.objects.filter(is_active=True, is_staff=True)]
        first_author = settings_obj.default_authors.first()

        return Response({
            "is_active": settings_obj.is_active,
            "articles_per_day": settings_obj.articles_per_day,
            "default_author_id": first_author.id if first_author else None,
            "categories": [cat.id for cat in settings_obj.categories.all()],
            "all_categories": categories_data,
            "all_authors": authors_data
        })

    def post(self, request, *args, **kwargs):
        settings_obj = AISettings.get_settings()
        
        is_active = request.data.get('is_active')
        articles_per_day = request.data.get('articles_per_day')
        default_author_id = request.data.get('default_author_id')
        categories_ids = request.data.get('categories', [])
        
        if is_active is not None:
            settings_obj.is_active = bool(is_active)
            
        if articles_per_day is not None:
            try:
                settings_obj.articles_per_day = int(articles_per_day)
            except ValueError:
                return Response({"error": "articles_per_day must be an integer"}, status=status.HTTP_400_BAD_REQUEST)
                
        if default_author_id is not None:
            if default_author_id == "":
                settings_obj.default_authors.clear()
            else:
                try:
                    settings_obj.default_authors.set([User.objects.get(id=default_author_id)])
                except User.DoesNotExist:
                    return Response({"error": "User does not exist"}, status=status.HTTP_400_BAD_REQUEST)

        settings_obj.save()

        if categories_ids is not None:
            settings_obj.categories.set(categories_ids)

        first_author = settings_obj.default_authors.first()
        return Response({
            "message": "Settings updated successfully",
            "is_active": settings_obj.is_active,
            "articles_per_day": settings_obj.articles_per_day,
            "default_author_id": first_author.id if first_author else None,
            "categories": [cat.id for cat in settings_obj.categories.all()]
        })

