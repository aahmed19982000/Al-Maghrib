from django.shortcuts import render, get_object_or_404
from django.views.generic import TemplateView, ListView, CreateView, UpdateView, DetailView, View
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseRedirect
from django.urls import reverse_lazy, reverse
from django.contrib import messages
from django.utils import timezone
from django.utils.text import slugify
from django.db.models import Q, Count, Sum, Value
from django.db.models.functions import Coalesce, TruncDate
from guardian.shortcuts import assign_perm

from news.models import Article, Category, Comment
from accounts.models import AuthorProfile
from .models import ActivityLog, ArticleRevision
from .forms import ArticleForm
from .forms_author import AuthorProfileForm

class DashboardAccessRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        user = self.request.user
        if not user.is_authenticated:
            return False
        if user.is_superuser or user.is_staff:
            return True
        # Allow if user has an active AuthorProfile
        return hasattr(user, 'author_profile') and user.author_profile.is_active

class DashboardHomeView(LoginRequiredMixin, DashboardAccessRequiredMixin, TemplateView):
    template_name = 'dashboard/home.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        
        # Check if user can view all articles (is staff/superuser or has can_edit_others)
        can_view_all = False
        if user.is_superuser or user.is_staff:
            can_view_all = True
        elif hasattr(user, 'author_profile') and user.author_profile.can_edit_others:
            can_view_all = True
            
        # Determine scope
        if can_view_all:
            articles = Article.objects.all()
            comments = Comment.objects.all()
            activities = ActivityLog.objects.all()
        else:
            articles = Article.objects.filter(author=user)
            comments = Comment.objects.filter(article__author=user)
            activities = ActivityLog.objects.filter(user=user)
            
        # Stats
        context['total_articles'] = articles.count()
        context['total_comments'] = comments.count()
        context['total_views'] = articles.aggregate(total=Sum('views_count'))['total'] or 0
        context['authors_count'] = AuthorProfile.objects.filter(is_active=True).count()
        
        # New KPIs: Created Today / Created This Week
        now = timezone.now()
        today_date = now.date()
        seven_days_ago = now - timezone.timedelta(days=7)
        context['articles_today'] = articles.filter(created_at__date=today_date).count()
        context['articles_this_week'] = articles.filter(created_at__gte=seven_days_ago).count()
        
        # New KPI: Visitor Mock Count (total views * 0.7)
        context['mock_visitors'] = int(context['total_views'] * 0.7)
        
        # Most Viewed Articles
        context['most_viewed_articles'] = articles.order_by('-views_count')[:5]
        
        # Pending Comments
        if can_view_all:
            context['pending_comments'] = Comment.objects.filter(is_approved=False).order_by('-created_at')[:5]
        else:
            context['pending_comments'] = Comment.objects.filter(article__author=user, is_approved=False).order_by('-created_at')[:5]
        
        # Status breakdown
        status_counts = articles.values('status').annotate(total=Count('id'))
        status_dict = {choice[0]: 0 for choice in Article.STATUS_CHOICES}
        for item in status_counts:
            status_dict[item['status']] = item['total']
        context['status_stats'] = status_dict
        
        # Calculate percentages for template styling
        total_count = context['total_articles']
        status_pct = {}
        for k, v in status_dict.items():
            status_pct[k] = int((v / total_count * 100)) if total_count > 0 else 0
        context['status_percentages'] = status_pct
        
        # Recent activities & recent articles
        context['recent_articles'] = articles.order_by('-created_at')[:5]
        context['recent_activities'] = activities.order_by('-timestamp')[:10]
        
        # Daily published counts over last 7 days for Chart.js
        date_list = [today_date - timezone.timedelta(days=i) for i in range(6, -1, -1)]
        pub_counts = articles.filter(
            status='published',
            published_at__date__gte=date_list[0]
        ).annotate(
            pub_date=TruncDate('published_at')
        ).values('pub_date').annotate(
            count=Count('id')
        )
        pub_count_map = {item['pub_date']: item['count'] for item in pub_counts if item['pub_date'] is not None}
        context['chart_pub_labels'] = [d.strftime('%Y-%m-%d') for d in date_list]
        context['chart_pub_data'] = [pub_count_map.get(d, 0) for d in date_list]
        
        # Category distribution counts for Chart.js
        cat_counts = articles.values('category__name').annotate(count=Count('id'))
        context['chart_cat_labels'] = [item['category__name'] for item in cat_counts if item['category__name'] is not None]
        context['chart_cat_data'] = [item['count'] for item in cat_counts]
        
        return context

class ArticleAdminView(LoginRequiredMixin, DashboardAccessRequiredMixin, ListView):
    model = Article
    template_name = 'dashboard/articles.html'
    context_object_name = 'articles'
    paginate_by = 10

    def get_queryset(self):
        user = self.request.user
        
        # Check if user can view all articles (is staff/superuser or has can_edit_others)
        can_view_all = False
        if user.is_superuser or user.is_staff:
            can_view_all = True
        elif hasattr(user, 'author_profile') and user.author_profile.can_edit_others:
            can_view_all = True
            
        if can_view_all:
            queryset = Article.objects.all()
        else:
            queryset = Article.objects.filter(author=user)
            
        # Filters and Search
        q = self.request.GET.get('q')
        status = self.request.GET.get('status')
        category = self.request.GET.get('category')
        
        if q:
            queryset = queryset.filter(
                Q(title_ar__icontains=q) | 
                Q(title_en__icontains=q) | 
                Q(body_ar__icontains=q) | 
                Q(body_en__icontains=q)
            )
        if status:
            queryset = queryset.filter(status=status)
        if category:
            queryset = queryset.filter(category_id=category)
            
        return queryset.order_by('-created_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['categories'] = Category.objects.filter(is_active=True)
        context['status_choices'] = Article.STATUS_CHOICES
        context['q'] = self.request.GET.get('q', '')
        context['selected_status'] = self.request.GET.get('status', '')
        context['selected_category'] = self.request.GET.get('category', '')
        return context

class ArticleCreateView(LoginRequiredMixin, DashboardAccessRequiredMixin, CreateView):
    model = Article
    form_class = ArticleForm
    template_name = 'dashboard/article_form.html'
    success_url = reverse_lazy('dashboard:articles')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        # Set author if not selected/allowed in form
        if 'author' not in form.fields:
            form.instance.author = self.request.user
            
        # Generate slug if empty
        if not form.instance.slug:
            title = form.cleaned_data.get('title_en') or form.cleaned_data.get('title_ar') or "article"
            form.instance.slug = slugify(title, allow_unicode=True)
            
        # Check slug uniqueness
        slug = form.instance.slug
        base_slug = slug
        counter = 1
        while Article.objects.filter(slug=slug).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1
        form.instance.slug = slug
        
        response = super().form_valid(form)
        
        # Assign object-level permissions to the author using django-guardian
        assign_perm('change_article', self.object.author, self.object)
        assign_perm('delete_article', self.object.author, self.object)
        
        ActivityLog.objects.create(
            user=self.request.user,
            action_type="إنشاء مقال",
            description=f"تم إنشاء المقال الجديد: {self.object.title}"
        )
        messages.success(self.request, "تم إنشاء المقال بنجاح.")
        return response

class ArticleUpdateView(LoginRequiredMixin, DashboardAccessRequiredMixin, UpdateView):
    model = Article
    form_class = ArticleForm
    template_name = 'dashboard/article_form.html'
    success_url = reverse_lazy('dashboard:articles')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def dispatch(self, request, *args, **kwargs):
        obj = self.get_object()
        # Enforce object-level permission check using django-guardian and Django permissions
        if not request.user.has_perm('news.change_article', obj):
            raise PermissionDenied("ليس لديك الصلاحية لتعديل هذا المقال.")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        # Generate slug if empty
        if not form.instance.slug:
            title = form.cleaned_data.get('title_en') or form.cleaned_data.get('title_ar') or "article"
            form.instance.slug = slugify(title, allow_unicode=True)
            
        # Check slug uniqueness
        slug = form.instance.slug
        base_slug = slug
        counter = 1
        while Article.objects.filter(slug=slug).exclude(pk=self.object.pk).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1
        form.instance.slug = slug
        
        response = super().form_valid(form)
        
        # Log revision snapshot
        ArticleRevision.objects.create(
            article=self.object,
            author=self.request.user,
            content_snapshot=f"AR Title: {self.object.title_ar}\nEN Title: {self.object.title_en}\nAR Body: {self.object.body_ar}\nEN Body: {self.object.body_en}",
            commit_message="Updated via HTML Dashboard"
        )
        
        ActivityLog.objects.create(
            user=self.request.user,
            action_type="تعديل مقال",
            description=f"تم تعديل المقال: {self.object.title}"
        )
        messages.success(self.request, "تم تحديث المقال بنجاح.")
        return response

class ArticlePreviewView(LoginRequiredMixin, DashboardAccessRequiredMixin, DetailView):
    model = Article
    template_name = 'dashboard/article_preview.html'
    context_object_name = 'article'

    def dispatch(self, request, *args, **kwargs):
        obj = self.get_object()
        # Enforce object-level permission check using django-guardian and Django permissions
        if not request.user.has_perm('news.view_article', obj):
            raise PermissionDenied("ليس لديك الصلاحية لمعاينة هذا المقال.")
        return super().dispatch(request, *args, **kwargs)

class ArticleBulkActionView(LoginRequiredMixin, DashboardAccessRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        action = request.POST.get('action')
        selected_ids = request.POST.getlist('selected_articles')
        
        if not selected_ids:
            messages.warning(request, "لم يتم تحديد أي مقالات.")
            return HttpResponseRedirect(reverse('dashboard:articles'))
            
        articles = Article.objects.filter(id__in=selected_ids)
        
        # Filter articles where the user has change_article permission
        authorized_articles = []
        for article in articles:
            if request.user.has_perm('news.change_article', article):
                authorized_articles.append(article)
                
        count = len(authorized_articles)
        if count == 0:
            messages.warning(request, "لم يتم العثور على مقالات صالحة لتعديلها أو لا تملك الصلاحية اللازمة.")
            return HttpResponseRedirect(reverse('dashboard:articles'))
            
        pks = [a.pk for a in authorized_articles]
        authorized_qs = Article.objects.filter(pk__in=pks)
        
        if action == 'publish':
            # Enforce can_publish permission per article
            for article in authorized_articles:
                if not request.user.has_perm('news.can_publish', article):
                    messages.error(request, f"ليس لديك صلاحية لنشر المقال: {article.title}")
                    return HttpResponseRedirect(reverse('dashboard:articles'))
            authorized_qs.update(status='published', published_at=timezone.now())
            messages.success(request, f"تم نشر {count} مقالات بنجاح.")
        elif action == 'draft':
            authorized_qs.update(status='draft')
            messages.success(request, f"تم تحويل {count} مقالات إلى مسودة.")
        elif action == 'review':
            authorized_qs.update(status='review')
            messages.success(request, f"تم إرسال {count} مقالات للمراجعة.")
        elif action == 'archive':
            authorized_qs.update(status='archived')
            messages.success(request, f"تم أرشفة {count} مقالات.")
        elif action == 'delete':
            # Check permissions for soft-deleting articles
            for article in authorized_articles:
                if not request.user.has_perm('news.delete_article', article):
                    messages.error(request, f"ليس لديك صلاحية لحذف المقال: {article.title}")
                    return HttpResponseRedirect(reverse('dashboard:articles'))
                
            # Loop to invoke the custom soft-delete logic
            for article in authorized_articles:
                article.delete()
            messages.success(request, f"تم نقل {count} مقالات لسلة المحذوفات (حذف مؤقت).")
        else:
            messages.error(request, "إجراء غير صالح.")
            
        ActivityLog.objects.create(
            user=request.user,
            action_type="إجراء جماعي",
            description=f"تم تنفيذ إجراء ({action}) على عدد ({count}) مقالات"
        )
        return HttpResponseRedirect(reverse('dashboard:articles'))

class CategoryTreeView(LoginRequiredMixin, DashboardAccessRequiredMixin, TemplateView):
    template_name = 'dashboard/categories.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['categories'] = Category.objects.all()
        return context

class AuthorStatsView(LoginRequiredMixin, DashboardAccessRequiredMixin, TemplateView):
    template_name = 'dashboard/author_stats.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        try:
            author_profile = self.request.user.author_profile
            articles = author_profile.user.articles.all()
            context['author'] = author_profile
            context['articles'] = articles
            context['total_articles'] = articles.count()
            context['total_views'] = articles.aggregate(total=Sum('views_count'))['total'] or 0
        except AuthorProfile.DoesNotExist:
            context['error'] = "لا تملك ملف كاتب نشط في الموقع."
        return context

# Management views for Authors (staff and admin only)
class AuthorManagementListView(LoginRequiredMixin, DashboardAccessRequiredMixin, ListView):
    model = AuthorProfile
    template_name = 'dashboard/authors_list.html'
    context_object_name = 'authors'

    def dispatch(self, request, *args, **kwargs):
        if not (request.user.is_superuser or request.user.is_staff):
            raise PermissionDenied("ليس لديك الصلاحية لإدارة الكتاب.")
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        # Annotate total articles and total views, filtering out deleted articles
        return AuthorProfile.objects.annotate(
            total_articles=Count('user__articles', filter=Q(user__articles__deleted_at__isnull=True)),
            total_views=Coalesce(Sum('user__articles__views_count', filter=Q(user__articles__deleted_at__isnull=True)), Value(0))
        ).order_by('-joined_date')

class AuthorManagementDetailView(LoginRequiredMixin, DashboardAccessRequiredMixin, View):
    template_name = 'dashboard/author_detail_mgmt.html'
    
    def dispatch(self, request, *args, **kwargs):
        if not (request.user.is_superuser or request.user.is_staff):
            raise PermissionDenied("ليس لديك الصلاحية لإدارة الكتاب.")
        return super().dispatch(request, *args, **kwargs)
        
    def get_author(self, pk):
        return get_object_or_404(AuthorProfile, pk=pk)
        
    def get(self, request, pk, *args, **kwargs):
        author = self.get_author(pk)
        form = AuthorProfileForm(instance=author)
        
        # Articles of this author with search/filtering
        articles = Article.objects.filter(author=author.user)
        
        q = request.GET.get('q')
        status = request.GET.get('status')
        category = request.GET.get('category')
        
        if q:
            articles = articles.filter(
                Q(title_ar__icontains=q) | 
                Q(title_en__icontains=q) |
                Q(body_ar__icontains=q) |
                Q(body_en__icontains=q)
            )
        if status:
            articles = articles.filter(status=status)
        if category:
            articles = articles.filter(category_id=category)
            
        articles = articles.order_by('-created_at')
        
        # Paginate articles
        from django.core.paginator import Paginator
        paginator = Paginator(articles, 10)
        page_number = request.GET.get('page')
        page_obj = paginator.get_page(page_number)
        
        # Aggregated stats
        total_articles = articles.count()
        total_views = articles.aggregate(total=Sum('views_count'))['total'] or 0
        
        categories = Category.objects.filter(is_active=True)
        
        context = {
            'author': author,
            'form': form,
            'page_obj': page_obj,
            'total_articles': total_articles,
            'total_views': total_views,
            'categories': categories,
            'status_choices': Article.STATUS_CHOICES,
            'q': q or '',
            'selected_status': status or '',
            'selected_category': category or '',
        }
        return render(request, self.template_name, context)
        
    def post(self, request, pk, *args, **kwargs):
        author = self.get_author(pk)
        form = AuthorProfileForm(request.POST, request.FILES, instance=author)
        if form.is_valid():
            form.save()
            messages.success(request, "تم تحديث بيانات الكاتب وصلاحياته بنجاح.")
            return HttpResponseRedirect(reverse('dashboard:author_detail_mgmt', kwargs={'pk': pk}))
        else:
            messages.error(request, "حدث خطأ في تحديث البيانات. يرجى مراجعة الحقول.")
            
            # Re-fetch articles and stats to render list
            articles = Article.objects.filter(author=author.user).order_by('-created_at')
            from django.core.paginator import Paginator
            paginator = Paginator(articles, 10)
            page_obj = paginator.get_page(1)
            total_articles = articles.count()
            total_views = articles.aggregate(total=Sum('views_count'))['total'] or 0
            categories = Category.objects.filter(is_active=True)
            
            context = {
                'author': author,
                'form': form,
                'page_obj': page_obj,
                'total_articles': total_articles,
                'total_views': total_views,
                'categories': categories,
                'status_choices': Article.STATUS_CHOICES,
            }
            return render(request, self.template_name, context)

class CommentActionView(LoginRequiredMixin, DashboardAccessRequiredMixin, View):
    def post(self, request, pk, *args, **kwargs):
        action = request.POST.get('action')
        comment = get_object_or_404(Comment, pk=pk)
        
        can_moderate = False
        if request.user.is_superuser or request.user.is_staff:
            can_moderate = True
        elif comment.article.author == request.user:
            can_moderate = True
            
        if not can_moderate:
            raise PermissionDenied("ليس لديك الصلاحية لإدارة التعليقات.")
            
        if action == 'approve':
            comment.is_approved = True
            comment.save()
            messages.success(request, "تمت الموافقة على التعليق بنجاح.")
        elif action == 'delete':
            comment.delete()
            messages.success(request, "تم حذف التعليق بنجاح.")
        else:
            messages.error(request, "إجراء غير صالح.")
            
        ActivityLog.objects.create(
            user=request.user,
            action_type="إدارة التعليقات",
            description=f"تم تنفيذ إجراء ({action}) على تعليق رقم #{pk} بواسطة @{comment.user.username}"
        )
        
        next_url = request.POST.get('next') or reverse('dashboard:home')
        return HttpResponseRedirect(next_url)
