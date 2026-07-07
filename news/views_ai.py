from django.shortcuts import render, redirect
from django.views.generic import ListView, CreateView, UpdateView, DeleteView, View, TemplateView
from django.contrib.auth.mixins import UserPassesTestMixin
from django.urls import reverse_lazy
from django.contrib import messages
from django.shortcuts import get_object_or_404
from .models import AISettings, AISource, AIImportLog, Category, Article, WordPressSite
from .ai_utils import run_ai_generation_cycle

class StaffRequiredMixin(UserPassesTestMixin):
    """
    Mixin that ensures the user is logged in and is a staff member.
    """
    login_url = '/accounts/login/' # Or wherever the login path is configured
    
    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.is_staff


class DashboardIndexView(StaffRequiredMixin, TemplateView):
    template_name = 'ai_dashboard/index.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Stats
        context['settings'] = AISettings.get_settings()
        context['sources_count'] = AISource.objects.count()
        context['active_sources_count'] = AISource.objects.filter(is_active=True).count()
        context['total_articles_generated'] = AIImportLog.objects.filter(status='success').count()
        context['total_failures'] = AIImportLog.objects.filter(status='failed').count()
        
        # Lists
        context['recent_articles'] = Article.objects.filter(ai_logs__isnull=False).distinct().order_by('-published_at')[:8]
        context['recent_logs'] = AIImportLog.objects.all().order_by('-created_at')[:10]
        
        return context


class SettingsUpdateView(StaffRequiredMixin, UpdateView):
    model = AISettings
    fields = ['gemini_api_key', 'telegram_bot_token', 'telegram_allowed_chats', 'articles_per_day', 'max_words', 'is_active']
    template_name = 'ai_dashboard/settings.html'
    success_url = reverse_lazy('news_ai:index')

    def get_object(self, queryset=None):
        return AISettings.get_settings()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from .models import WordPressSite
        context['wp_sites'] = WordPressSite.objects.filter(is_active=True)
        context['all_sources'] = AISource.objects.filter(is_active=True)
        context['local_source_ids'] = list(self.get_object().local_sources.values_list('id', flat=True))
        return context

    def form_valid(self, form):
        from .models import WordPressSite
        response = super().form_valid(form)
        
        # Save local_sources M2M selection
        settings_obj = self.get_object()
        selected_local_sources = self.request.POST.getlist('local_sources')
        settings_obj.local_sources.set(
            AISource.objects.filter(id__in=[int(x) for x in selected_local_sources if x.isdigit()])
        )

        # Process and save WordPress site limits from POST
        active_sites = WordPressSite.objects.filter(is_active=True)
        for site in active_sites:
            limit_key = f"site_limit_{site.id}"
            if limit_key in self.request.POST:
                try:
                    val = int(self.request.POST[limit_key])
                    if val >= 0:
                        site.daily_limit = val
                        site.save()
                except (ValueError, TypeError):
                    pass
                    
        messages.success(self.request, "تم حفظ الإعدادات بنجاح.")
        return response


class SourceListView(StaffRequiredMixin, ListView):
    model = AISource
    template_name = 'ai_dashboard/sources_list.html'
    context_object_name = 'sources'


class SourceCreateView(StaffRequiredMixin, CreateView):
    model = AISource
    fields = ['name', 'url', 'language', 'is_active']
    template_name = 'ai_dashboard/source_form.html'
    success_url = reverse_lazy('news_ai:sources')

    def form_valid(self, form):
        messages.success(self.request, f"تمت إضافة المصدر '{form.instance.name}' بنجاح.")
        return super().form_valid(form)


class SourceUpdateView(StaffRequiredMixin, UpdateView):
    model = AISource
    fields = ['name', 'url', 'language', 'is_active']
    template_name = 'ai_dashboard/source_form.html'
    success_url = reverse_lazy('news_ai:sources')

    def form_valid(self, form):
        messages.success(self.request, f"تم تحديث المصدر '{form.instance.name}' بنجاح.")
        return super().form_valid(form)


class SourceDeleteView(StaffRequiredMixin, DeleteView):
    model = AISource
    template_name = 'ai_dashboard/source_confirm_delete.html'
    success_url = reverse_lazy('news_ai:sources')

    def delete(self, request, *args, **kwargs):
        obj = self.get_object()
        messages.success(self.request, f"تم حذف المصدر '{obj.name}' بنجاح.")
        return super().delete(request, *args, **kwargs)


class ImportLogListView(StaffRequiredMixin, ListView):
    model = AIImportLog
    template_name = 'ai_dashboard/logs_list.html'
    context_object_name = 'logs'
    paginate_by = 25


class TriggerScraperView(StaffRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        try:
            count = run_ai_generation_cycle()
            if count > 0:
                messages.success(request, f"تم تشغيل النظام بنجاح وتوليد {count} أخبار جديدة ونشرها.")
            else:
                messages.info(request, "تم تشغيل النظام ولكن لم يتم توليد أي أخبار جديدة (ربما لم يتبقَ أخبار جديدة اليوم أو تم الوصول للحد اليومي).")
        except Exception as e:
            messages.error(request, f"فشل تشغيل عملية التوليد الآلية: {str(e)}")
            
        return redirect('news_ai:index')
    
    def get(self, request, *args, **kwargs):
        return redirect('news_ai:index')


class WordPressSiteListView(StaffRequiredMixin, ListView):
    model = WordPressSite
    template_name = 'ai_dashboard/wp_sites_list.html'
    context_object_name = 'sites'


class WordPressSiteCreateView(StaffRequiredMixin, CreateView):
    model = WordPressSite
    fields = ['name', 'url', 'username', 'application_password', 'daily_limit', 'is_active', 'sources', 'category_mapping']
    template_name = 'ai_dashboard/wp_site_form.html'
    success_url = reverse_lazy('news_ai:wp_sites')

    def form_valid(self, form):
        messages.success(self.request, f"تمت إضافة الموقع '{form.instance.name}' بنجاح.")
        return super().form_valid(form)


class WordPressSiteUpdateView(StaffRequiredMixin, UpdateView):
    model = WordPressSite
    fields = ['name', 'url', 'username', 'application_password', 'daily_limit', 'is_active', 'sources', 'category_mapping']
    template_name = 'ai_dashboard/wp_site_form.html'
    success_url = reverse_lazy('news_ai:wp_sites')

    def form_valid(self, form):
        messages.success(self.request, f"تم تحديث الموقع '{form.instance.name}' بنجاح.")
        return super().form_valid(form)


class WordPressSiteDeleteView(StaffRequiredMixin, DeleteView):
    model = WordPressSite
    template_name = 'ai_dashboard/wp_site_confirm_delete.html'
    success_url = reverse_lazy('news_ai:wp_sites')

    def delete(self, request, *args, **kwargs):
        obj = self.get_object()
        messages.success(self.request, f"تم حذف الموقع '{obj.name}' بنجاح.")
        return super().delete(request, *args, **kwargs)

