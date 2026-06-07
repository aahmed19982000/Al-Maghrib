from django.urls import path
from django.http import HttpResponse
from django.views.decorators.cache import cache_page
from .views import HomepageView, SearchView, ContactView, AboutView, NewsletterSubscribeView, CharterView, ContactOfficeView, PrivacyPolicyView, TermsView, ArchiveView

app_name = 'core'

urlpatterns = [
    path('', HomepageView.as_view(), name='home'),
    path('search/', SearchView.as_view(), name='search'),
    path('contact/', ContactView.as_view(), name='contact'),
    path('contact/success/', lambda r: HttpResponse("Success"), name='contact_success'), # Quick dummy success URL
    path('about/', AboutView.as_view(), name='about'),
    path('newsletter/subscribe/', NewsletterSubscribeView.as_view(), name='newsletter_subscribe'),
    path('charter/', CharterView.as_view(), name='charter'),
    path('contact-office/', ContactOfficeView.as_view(), name='contact_office'),
    path('privacy-policy/', PrivacyPolicyView.as_view(), name='privacy_policy'),
    path('terms/', TermsView.as_view(), name='terms'),
    path('archive/', ArchiveView.as_view(), name='archive'),
    path('robots.txt', lambda r: HttpResponse(f"User-agent: *\nDisallow: /admin/\nDisallow: /dashboard/\nSitemap: {r.scheme}://{r.get_host()}/sitemap.xml", content_type="text/plain")),
]
