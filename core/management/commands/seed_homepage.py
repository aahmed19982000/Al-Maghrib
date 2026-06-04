from django.core.management.base import BaseCommand
from news.models import Category
from core.models import HomePageCategory, HomePageSettings
from django.utils.text import slugify

class Command(BaseCommand):
    help = 'Seeds the database with exact categories and layouts from the design.'

    def handle(self, *args, **options):
        # Clear existing
        HomePageCategory.objects.all().delete()

        # Map design names to styles
        designs = [
            ("آخر الأخبار", "featured_grid", 5),
            ("تحليلات إقليمية", "dark_cards", 3),
            ("اقتصاد", "mixed_grid", 5),
            ("ثقافة وتراث", "tall_cards", 3),
            ("رياضة", "simple_cards", 4),
            ("تغطية الدول", "country_cards", 5)
        ]

        for order, (cat_name, style, count) in enumerate(designs):
            # Try to find existing category first, or create
            cat = Category.objects.filter(name=cat_name).first()
            if not cat:
                slug = cat_name.replace(' ', '-')
                cat = Category.objects.create(name=cat_name, slug=slug)

            # Create homepage setting
            HomePageCategory.objects.create(
                category=cat,
                order=order,
                design_style=style,
                article_count=count,
                is_active=True
            )
            self.stdout.write(f"Added {cat_name} with {style}")

        settings = HomePageSettings.load()
        settings.show_slider = True
        settings.show_breaking_news = True
        settings.save()
        self.stdout.write(self.style.SUCCESS("Done seeding homepage layout."))
