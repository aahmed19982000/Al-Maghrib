from django.contrib.sitemaps import Sitemap
from django.urls import reverse
from news.models import Article, Category

class ArticleSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.8

    def items(self):
        return Article.objects.filter(status='published').order_by('-published_at')

    def lastmod(self, obj):
        return obj.updated_at

class CategorySitemap(Sitemap):
    changefreq = "monthly"
    priority = 0.6

    def items(self):
        return Category.objects.filter(is_active=True)

class StaticSitemap(Sitemap):
    changefreq = "daily"
    priority = 1.0

    def items(self):
        # Named URL patterns to include in the sitemap
        return ['core:home', 'core:about', 'core:contact']

    def location(self, item):
        return reverse(item)
