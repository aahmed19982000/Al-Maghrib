from django.core.management.base import BaseCommand
from news.ai_utils import run_ai_generation_cycle

class Command(BaseCommand):
    help = 'Executes a single cycle of scraping RSS feeds and generating AI news articles'

    def handle(self, *args, **options):
        self.stdout.write("Starting AI news generation cycle...")
        try:
            count = run_ai_generation_cycle()
            self.stdout.write(self.style.SUCCESS(f"Successfully finished cycle. Generated {count} articles."))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error during AI generation cycle: {str(e)}"))
