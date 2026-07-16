from django.shortcuts import render, get_object_or_404
from django.views.generic import DetailView, ListView
from django.views import View
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.http import HttpResponseRedirect
from .models import Article, Category, Comment, Like, Bookmark
from accounts.models import AuthorProfile

class ArticleDetailView(DetailView):
    model = Article
    template_name = 'news/article_detail.html'
    context_object_name = 'article'

    def get_queryset(self):
        return Article.objects.filter(status='published')

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        # Increment views count
        obj.views_count += 1
        obj.save(update_fields=['views_count'])
        return obj

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        article = self.get_object()
        
        # Breadcrumbs
        breadcrumbs = []
        if article.category:
            for ancestor in article.category.get_ancestors(include_self=True):
                breadcrumbs.append({
                    'name': ancestor.name,
                    'url': ancestor.get_absolute_url()
                })
        breadcrumbs.append({
            'name': article.title,
            'url': ''
        })
        context['breadcrumbs'] = breadcrumbs
        
        # Related articles (same category, excluding this one)
        context['related_articles'] = Article.objects.filter(
            status='published', 
            category=article.category
        ).exclude(id=article.id).order_by('-published_at')[:4]
        
        # Approved top-level comments
        context['comments'] = article.comments.filter(is_approved=True, parent=None).order_by('-created_at')
        
        # Check if user liked/bookmarked
        if self.request.user.is_authenticated:
            context['user_has_liked'] = Like.objects.filter(article=article, user=self.request.user).exists()
            context['user_has_bookmarked'] = Bookmark.objects.filter(article=article, user=self.request.user).exists()
        else:
            context['user_has_liked'] = False
            context['user_has_bookmarked'] = False
        
        # Like & Bookmark counts
        context['likes_count'] = article.likes.count()
        context['bookmarks_count'] = article.bookmarks.count()
        
        return context

class CategoryListView(ListView):
    model = Article
    template_name = 'news/category_list.html'
    context_object_name = 'articles'
    paginate_by = 12

    def get_queryset(self):
        self.category = get_object_or_404(Category, slug=self.kwargs['slug'])
        # Get category and all its subcategories
        categories = self.category.get_descendants(include_self=True)
        queryset = Article.objects.filter(
            Q(category__in=categories) | Q(additional_categories__in=categories),
            status='published'
        ).distinct()
        
        # Sort selection
        self.sort_by = self.request.GET.get('sort', 'latest')
        if self.sort_by == 'popular':
            queryset = queryset.order_by('-views_count')
        else:
            queryset = queryset.order_by('-published_at')
            
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['category'] = self.category
        context['sort_by'] = self.sort_by
        
        # Build category breadcrumbs
        breadcrumbs = []
        for ancestor in self.category.get_ancestors(include_self=True):
            breadcrumbs.append({
                'name': ancestor.name,
                'url': ancestor.get_absolute_url()
            })
        context['breadcrumbs'] = breadcrumbs
        return context

class ArticleListView(ListView):
    model = Article
    template_name = 'news/article_list.html'
    context_object_name = 'articles'
    paginate_by = 12

    def get_queryset(self):
        return Article.objects.filter(status='published').order_by('-published_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['breadcrumbs'] = [
            {'name': _('كل المقالات'), 'url': ''}
        ]
        return context

class BreakingNewsView(ListView):
    model = Article
    template_name = 'news/breaking_news.html'
    context_object_name = 'articles'
    paginate_by = 10

    def get_queryset(self):
        return Article.objects.filter(status='published').order_by('-published_at')

class AuthorDetailView(ListView):
    template_name = 'news/author_detail.html'
    context_object_name = 'articles'
    paginate_by = 12

    def get_queryset(self):
        self.author_profile = get_object_or_404(AuthorProfile, pk=self.kwargs['pk'])
        queryset = Article.objects.filter(author=self.author_profile.user, status='published').order_by('-published_at')
        
        # Filtering
        q = self.request.GET.get('q')
        category_slug = self.request.GET.get('category')
        
        if q:
            queryset = queryset.filter(
                Q(title_ar__icontains=q) | 
                Q(title_en__icontains=q) | 
                Q(body_ar__icontains=q) | 
                Q(body_en__icontains=q)
            )
        if category_slug:
            category = get_object_or_404(Category, slug=category_slug)
            categories = category.get_descendants(include_self=True)
            queryset = queryset.filter(
                Q(category__in=categories) | Q(additional_categories__in=categories)
            ).distinct()
            
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from core.models import SiteSettings
        context['author'] = self.author_profile
        context['categories'] = Category.objects.filter(is_active=True)
        context['site_settings'] = SiteSettings.load()
        context['q'] = self.request.GET.get('q', '')
        context['selected_category'] = self.request.GET.get('category', '')
        
        # Add breadcrumbs for Author Detail
        context['breadcrumbs'] = [
            {'name': _('الكتاب'), 'url': ''},
            {'name': str(self.author_profile), 'url': ''}
        ]
        return context

class CommentSubmitView(LoginRequiredMixin, View):
    def post(self, request, slug):
        article = get_object_or_404(Article, slug=slug, status='published')
        body = request.POST.get('body')
        parent_id = request.POST.get('parent_id')
        
        if body:
            parent = None
            if parent_id:
                try:
                    parent = Comment.objects.get(id=parent_id, article=article)
                except Comment.DoesNotExist:
                    pass
            
            Comment.objects.create(
                article=article,
                user=request.user,
                body=body,
                parent=parent,
                is_approved=True
            )
            messages.success(request, _("تم إضافة تعليقك بنجاح!"))
        else:
            messages.error(request, _("لا يمكن إضافة تعليق فارغ."))
            
        return HttpResponseRedirect(article.get_absolute_url())

class ArticleLikeToggleView(LoginRequiredMixin, View):
    def post(self, request, slug):
        article = get_object_or_404(Article, slug=slug, status='published')
        like_obj, created = Like.objects.get_or_create(article=article, user=request.user)
        if not created:
            like_obj.delete()
            messages.info(request, _("تم إزالة الإعجاب بالمقال."))
        else:
            messages.success(request, _("تم تسجيل إعجابك بالمقال!"))
        return HttpResponseRedirect(article.get_absolute_url())

class ArticleBookmarkToggleView(LoginRequiredMixin, View):
    def post(self, request, slug):
        article = get_object_or_404(Article, slug=slug, status='published')
        bookmark_obj, created = Bookmark.objects.get_or_create(article=article, user=request.user)
        if not created:
            bookmark_obj.delete()
            messages.info(request, _("تم إزالة المقال من المحفوظات."))
        else:
            messages.success(request, _("تم حفظ المقال في مفضلتك!"))
        return HttpResponseRedirect(article.get_absolute_url())
