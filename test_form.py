import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'almaghrib.settings')
django.setup()

from dashboard.forms import ArticleForm

form = ArticleForm()
print(form.fields.keys())
print("auto_translate in form.fields:", 'auto_translate' in form.fields)
print("HTML for auto_translate:", form['auto_translate'])
