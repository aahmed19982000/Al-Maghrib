from .models import Category
from core.models import SiteSettings

def global_context(request):
    return {
        'global_categories': Category.objects.filter(is_active=True, parent__isnull=True).order_by('order', 'name'),
        'site_settings': SiteSettings.load(),
    }
