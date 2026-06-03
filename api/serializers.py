from rest_framework import serializers
from django.contrib.auth.models import User
from accounts.models import AuthorProfile
from news.models import Category, Article

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'username', 'first_name', 'last_name', 'email')

class AuthorProfileSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)

    class Meta:
        model = AuthorProfile
        fields = ('id', 'user', 'display_name', 'bio', 'avatar', 'role', 'twitter', 
                  'linkedin', 'email_public', 'specialization', 'is_active', 
                  'joined_date', 'articles_count')

class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ('id', 'name', 'slug', 'parent', 'level')

class ArticleSerializer(serializers.ModelSerializer):
    author = AuthorProfileSerializer(read_only=True)
    category = CategorySerializer(read_only=True)
    tags = serializers.SlugRelatedField(many=True, read_only=True, slug_field='name')

    class Meta:
        model = Article
        fields = ('id', 'title', 'slug', 'body', 'excerpt', 'cover_image', 
                  'author', 'category', 'tags', 'status', 'published_at', 
                  'created_at', 'updated_at', 'views_count', 'read_time',
                  'is_featured', 'is_breaking', 'allow_comments', 'meta_title', 'meta_desc')
