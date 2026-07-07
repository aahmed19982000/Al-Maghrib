from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

# URL patterns for the AI Subdomain (ai.almaghrib.com / ai.localhost)
urlpatterns = [
    # Include the AI dashboard paths
    path('', include('news.urls_ai')),
    
    # We can also expose django admin and ckeditor on this subdomain if needed
    path('admin/', admin.site.urls),
    path('ckeditor5/', include('django_ckeditor_5.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
