import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'almaghrib.settings')
django.setup()

from news.models import Category
from core.models import HomePageCategory, HomePageSettings

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
    # Get or create category
    cat, _ = Category.objects.get_or_create(name=cat_name, defaults={'slug': cat_name.replace(' ', '-')})
    # Create homepage setting
    HomePageCategory.objects.create(
        category=cat,
        order=order,
        design_style=style,
        article_count=count,
        is_active=True
    )
    print(f"Added {cat_name} with {style}")

settings = HomePageSettings.load()
settings.show_slider = True
settings.show_breaking_news = True
settings.save()
print("Done seeding homepage layout.")
