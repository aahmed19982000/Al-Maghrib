from django.shortcuts import render
from django.views.generic import TemplateView, ListView, FormView
from django import forms
from django.urls import reverse_lazy
from django.http import HttpResponse
from django.utils.translation import gettext_lazy as _
from news.models import Article, Category
from accounts.models import AuthorProfile

class ContactForm(forms.Form):
    name = forms.CharField(max_length=100)
    email = forms.EmailField()
    subject = forms.CharField(max_length=255)
    message = forms.CharField(widget=forms.Textarea)
    captcha = forms.CharField(max_length=20)

class HomepageView(TemplateView):
    template_name = 'core/home.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Fetch breaking, featured, popular, and latest published articles
        context['latest_articles'] = Article.objects.filter(status='published').order_by('-published_at')[:10]
        context['featured_articles'] = Article.objects.filter(status='published', is_featured=True).order_by('-published_at')[:4]
        context['breaking_articles'] = Article.objects.filter(status='published', is_breaking=True).order_by('-published_at')[:5]
        context['popular_articles'] = Article.objects.filter(status='published').order_by('-views_count')[:5]
        context['slider_articles'] = Article.objects.filter(status='published', cover_image__gt='').order_by('-published_at')[:5]
        
        # Categorized news columns
        categories_data = []
        for cat in Category.objects.filter(is_active=True, parent=None)[:5]:
            articles = Article.objects.filter(category__in=cat.get_descendants(include_self=True), status='published').order_by('-published_at')[:4]
            if articles.exists():
                categories_data.append({
                    'category': cat,
                    'articles': articles
                })
        context['categories_data'] = categories_data
        
        # Sidebar Ad
        from core.models import Advertisement
        context['sidebar_ad'] = Advertisement.objects.filter(slot='sidebar', is_active=True).first()
        
        context['authors'] = AuthorProfile.objects.filter(is_active=True)[:6]
        return context

class SearchView(ListView):
    model = Article
    template_name = 'core/search.html'
    context_object_name = 'articles'
    paginate_by = 10

    def get_queryset(self):
        query = self.request.GET.get('q', '')
        if query:
            return Article.objects.filter(status='published', title__icontains=query) | Article.objects.filter(status='published', body__icontains=query)
        return Article.objects.none()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['query'] = self.request.GET.get('q', '')
        context['breadcrumbs'] = [
            {'name': _('البحث'), 'url': ''}
        ]
        return context

class ContactView(FormView):
    template_name = 'core/contact.html'
    form_class = ContactForm
    success_url = reverse_lazy('core:contact')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['breadcrumbs'] = [
            {'name': _('اتصل بنا'), 'url': ''}
        ]
        
        # Generate simple math CAPTCHA
        import random
        num1 = random.randint(1, 9)
        num2 = random.randint(1, 9)
        self.request.session['captcha_result'] = num1 + num2
        context['captcha_question'] = f"{num1} + {num2} = ?"
        
        return context

    def form_valid(self, form):
        # Validate CAPTCHA
        session_captcha = self.request.session.get('captcha_result')
        user_captcha = form.cleaned_data.get('captcha')
        
        if not session_captcha or str(user_captcha).strip() != str(session_captcha):
            messages.error(self.request, _("رمز التحقق (CAPTCHA) غير صحيح. يرجى المحاولة مرة أخرى."))
            return self.form_invalid(form)
            
        name = form.cleaned_data['name']
        email = form.cleaned_data['email']
        subject = form.cleaned_data['subject']
        message = form.cleaned_data['message']
        
        # Build email content
        email_body = f"الاسم: {name}\nالبريد الإلكتروني: {email}\nالموضوع: {subject}\n\nالرسالة:\n{message}"
        
        # Send email via Django Mail
        from django.core.mail import send_mail
        from django.conf import settings
        
        try:
            send_mail(
                subject=f"[اتصل بنا] {subject}",
                message=email_body,
                from_email=settings.DEFAULT_FROM_EMAIL if hasattr(settings, 'DEFAULT_FROM_EMAIL') else 'noreply@almaghrib.com',
                recipient_list=[settings.CONTACT_EMAIL] if hasattr(settings, 'CONTACT_EMAIL') and settings.CONTACT_EMAIL else ['contact@almaghrib.com'],
                fail_silently=False,
            )
            messages.success(self.request, _("تم إرسال رسالتكم بنجاح! سنتواصل معكم في أقرب وقت."))
        except Exception:
            # Fallback for development if SMTP is not configured
            messages.success(self.request, _("تم استلام رسالتكم بنجاح! (نمط التطوير الفعال)"))
            
        return super().form_valid(form)

class AboutView(TemplateView):
    template_name = 'core/about.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['breadcrumbs'] = [
            {'name': _('من نحن'), 'url': ''}
        ]
        return context

from core.models import Newsletter
from django.views import View
from django.contrib import messages
from django.http import HttpResponseRedirect

class NewsletterSubscribeView(View):
    def post(self, request, *args, **kwargs):
        email = request.POST.get('email')
        if email:
            sub, created = Newsletter.objects.get_or_create(email=email)
            if created:
                messages.success(request, "تم الاشتراك في النشرة البريدية بنجاح!")
            else:
                messages.info(request, "أنت مشترك بالفعل في النشرة البريدية!")
        else:
            messages.error(request, "يرجى كتابة بريد إلكتروني صالح.")
            
        next_url = request.META.get('HTTP_REFERER') or '/'
        return HttpResponseRedirect(next_url)
