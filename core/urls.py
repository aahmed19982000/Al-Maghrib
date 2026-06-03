from django.urls import path
from django.http import HttpResponse
from django.views.decorators.cache import cache_page
from .views import HomepageView, SearchView, ContactView, AboutView, NewsletterSubscribeView

app_name = 'core'

urlpatterns = [
    path('', cache_page(60 * 15)(HomepageView.as_view()), name='home'),
    path('search/', SearchView.as_view(), name='search'),
    path('contact/', ContactView.as_view(), name='contact'),
    path('contact/success/', lambda r: HttpResponse("Success"), name='contact_success'), # Quick dummy success URL
    path('about/', AboutView.as_view(), name='about'),
    path('newsletter/subscribe/', NewsletterSubscribeView.as_view(), name='newsletter_subscribe'),
    path('robots.txt', lambda r: HttpResponse(f"User-agent: *\nDisallow: /admin/\nDisallow: /dashboard/\nSitemap: {r.scheme}://{r.get_host()}/sitemap.xml", content_type="text/plain")),
]
