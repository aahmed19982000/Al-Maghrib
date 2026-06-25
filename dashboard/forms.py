from django import forms
from django_ckeditor_5.widgets import CKEditor5Widget
from news.models import Article, Category
from django.contrib.auth.models import User

class ArticleForm(forms.ModelForm):
    class Meta:
        model = Article
        fields = [
            'title_ar', 'title_en',
            'slug',
            'author',
            'body_ar', 'body_en',
            'excerpt_ar', 'excerpt_en',
            'category', 'additional_categories',
            'status', 'is_featured', 'is_breaking', 'auto_translate',
            'cover_image', 'allow_comments',
            'meta_title_ar', 'meta_title_en',
            'meta_desc_ar', 'meta_desc_en'
        ]
        widgets = {
            'title_ar': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'العنوان بالعربية'}),
            'title_en': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Title in English'}),
            'slug': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'slug-url'}),
            'author': forms.Select(attrs={'class': 'form-control'}),
            'body_ar': CKEditor5Widget(config_name='extends', attrs={'class': 'django_ckeditor_5'}),
            'body_en': CKEditor5Widget(config_name='extends_en', attrs={'class': 'django_ckeditor_5'}),
            'excerpt_ar': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'المقتطف بالعربية'}),
            'excerpt_en': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Excerpt in English'}),
            'category': forms.Select(attrs={'class': 'form-control'}),
            'additional_categories': forms.SelectMultiple(attrs={'class': 'form-control', 'style': 'height: 100px;'}),
            'status': forms.Select(attrs={'class': 'form-control'}),
            'meta_title_ar': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'عنوان سيو بالعربية'}),
            'meta_title_en': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'SEO Title in English'}),
            'meta_desc_ar': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'وصف سيو بالعربية'}),
            'meta_desc_en': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'SEO Description in English'}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        # Ensure category queryset is loaded and has a hierarchy
        self.fields['category'].queryset = Category.objects.filter(is_active=True)
        self.fields['additional_categories'].queryset = Category.objects.filter(is_active=True)
        self.fields['additional_categories'].label = "الأقسام الإضافية (اختياري)"
        
        # Check permissions for Author assignment
        can_assign_author = False
        if self.user:
            if self.user.is_superuser or self.user.is_staff:
                can_assign_author = True
            elif hasattr(self.user, 'author_profile') and self.user.author_profile.can_edit_others:
                can_assign_author = True
                
        if can_assign_author:
            self.fields['author'].queryset = User.objects.filter(is_active=True)
            self.fields['author'].label = "الكاتب المسؤول (Author)"
        else:
            if 'author' in self.fields:
                del self.fields['author']
                
        # Check permissions for Direct Publishing
        can_publish = False
        if self.user:
            if self.user.is_superuser or self.user.is_staff:
                can_publish = True
            elif hasattr(self.user, 'author_profile') and self.user.author_profile.can_publish_directly:
                can_publish = True
                
        if not can_publish:
            current_status = self.instance.status if self.instance.pk else None
            choices = [('draft', 'مسودة (Draft)'), ('review', 'مراجعة (Review)')]
            if current_status == 'published':
                choices.append(('published', 'منشور (Published)'))
            if current_status == 'archived':
                choices.append(('archived', 'مؤرشف (Archived)'))
            self.fields['status'].choices = choices
            if not self.instance.pk:
                self.fields['status'].initial = 'draft'
            
        # Customize standard labels
        self.fields['title_ar'].label = "العنوان (عربي)"
        self.fields['title_en'].label = "Title (English)"
        self.fields['body_ar'].label = "المحتوى (عربي)"
        self.fields['body_en'].label = "Content (English)"
        self.fields['excerpt_ar'].label = "مقتطف (عربي)"
        self.fields['excerpt_en'].label = "Excerpt (English)"
        self.fields['meta_title_ar'].label = "عنوان SEO (عربي)"
        self.fields['meta_title_en'].label = "SEO Title (English)"
        self.fields['meta_desc_ar'].label = "وصف SEO (عربي)"
        self.fields['meta_desc_en'].label = "SEO Description (English)"
        self.fields['auto_translate'].label = "الترجمة التلقائية للإنجليزية (Auto-translate)"
        self.fields['cover_image'].widget.attrs.update({'class': 'form-control'})

class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = [
            'name_ar', 'name_en',
            'slug',
            'icon',
            'parent',
            'is_active',
            'order',
            'color',
            'meta_title_ar', 'meta_title_en',
            'meta_description_ar', 'meta_description_en',
            'meta_keywords_ar', 'meta_keywords_en'
        ]
        widgets = {
            'name_ar': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'اسم القسم بالعربية'}),
            'name_en': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Category name in English'}),
            'slug': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'slug-url'}),
            'icon': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. folder, article, info'}),
            'parent': forms.Select(attrs={'class': 'form-control'}),
            'order': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'color': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '#3b82f6 or class name'}),
            'meta_title_ar': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'عنوان سيو بالعربية'}),
            'meta_title_en': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'SEO Title in English'}),
            'meta_description_ar': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'وصف سيو بالعربية'}),
            'meta_description_en': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'SEO Description in English'}),
            'meta_keywords_ar': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'كلمات مفتاحية بالعربية'}),
            'meta_keywords_en': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Keywords in English'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name_ar'].label = "اسم القسم (عربي)"
        self.fields['name_en'].label = "Name (English)"
        self.fields['slug'].label = "الرابط الفرعي (Slug)"
        self.fields['icon'].label = "الأيقونة (Material Symbol / CSS class)"
        self.fields['parent'].label = "القسم الأب (Parent Category)"
        self.fields['is_active'].label = "نشط"
        self.fields['order'].label = "ترتيب العرض"
        self.fields['color'].label = "اللون المميز (Color)"
        self.fields['meta_title_ar'].label = "عنوان SEO (عربي)"
        self.fields['meta_title_en'].label = "SEO Title (English)"
        self.fields['meta_description_ar'].label = "وصف SEO (عربي)"
        self.fields['meta_description_en'].label = "SEO Description (English)"
        self.fields['meta_keywords_ar'].label = "كلمات SEO الدلالية (عربي)"
        self.fields['meta_keywords_en'].label = "SEO Keywords (English)"
        
        # Make parent, icon, color, etc. optional
        self.fields['parent'].required = False
        self.fields['icon'].required = False
        self.fields['color'].required = False
        self.fields['order'].required = False
        
        # Prevent circular parent relationships
        if self.instance and self.instance.pk:
            self.fields['parent'].queryset = Category.objects.exclude(pk=self.instance.pk)

from django.forms.models import modelformset_factory
from core.models import HomePageSettings, HomePageCategory

class HomePageSettingsForm(forms.ModelForm):
    class Meta:
        model = HomePageSettings
        fields = [
            'seo_title_ar', 'seo_title_en',
            'seo_description_ar', 'seo_description_en',
            'seo_keywords_ar', 'seo_keywords_en',
            'show_breaking_news', 'show_slider', 'show_featured', 'show_popular',
            'show_authors_section', 'authors_section_title', 'featured_authors', 'authors_section_order',
            'slider_count', 'featured_count', 'popular_count'
        ]
        widgets = {
            'seo_title_ar': forms.TextInput(attrs={'class': 'form-control'}),
            'seo_title_en': forms.TextInput(attrs={'class': 'form-control'}),
            'seo_description_ar': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'seo_description_en': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'seo_keywords_ar': forms.TextInput(attrs={'class': 'form-control'}),
            'seo_keywords_en': forms.TextInput(attrs={'class': 'form-control'}),
            'authors_section_order': forms.NumberInput(attrs={'class': 'form-control'}),
            'slider_count': forms.NumberInput(attrs={'class': 'form-control'}),
            'featured_count': forms.NumberInput(attrs={'class': 'form-control'}),
            'popular_count': forms.NumberInput(attrs={'class': 'form-control'}),
            'authors_section_title': forms.TextInput(attrs={'class': 'form-control'}),
            'featured_authors': forms.SelectMultiple(attrs={'class': 'form-control', 'style': 'height: 150px;'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['seo_title_ar'].label = "عنوان SEO للصفحة الرئيسية (عربي)"
        self.fields['seo_title_en'].label = "SEO Title (English)"
        self.fields['seo_description_ar'].label = "وصف SEO (عربي)"
        self.fields['seo_description_en'].label = "SEO Description (English)"
        self.fields['seo_keywords_ar'].label = "الكلمات المفتاحية (عربي)"
        self.fields['seo_keywords_en'].label = "SEO Keywords (English)"
        self.fields['show_breaking_news'].label = "عرض شريط الأخبار العاجلة"
        self.fields['show_slider'].label = "عرض المعرض (Slider)"
        self.fields['show_featured'].label = "عرض التحليلات المميزة"
        self.fields['show_popular'].label = "عرض الأخبار الأكثر تداولاً"
        self.fields['show_authors_section'].label = "عرض قسم الكتاب"
        self.fields['authors_section_title'].label = "عنوان قسم الكتاب"
        self.fields['featured_authors'].label = "اختر الكتاب لعرضهم (اتركه فارغاً لعرض أحدث الكتاب)"
        self.fields['authors_section_order'].label = "ترتيب قسم الكتاب"
        self.fields['slider_count'].label = "عدد الأخبار في المعرض"
        self.fields['featured_count'].label = "عدد التحليلات المميزة"
        self.fields['popular_count'].label = "عدد الأخبار الأكثر تداولاً"

class HomePageCategoryForm(forms.ModelForm):
    class Meta:
        model = HomePageCategory
        fields = ['category', 'order', 'design_style', 'article_count', 'is_active']
        widgets = {
            'category': forms.Select(attrs={'class': 'form-control'}),
            'order': forms.NumberInput(attrs={'class': 'form-control'}),
            'design_style': forms.Select(attrs={'class': 'form-control'}),
            'article_count': forms.NumberInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['category'].label = "القسم"
        self.fields['order'].label = "الترتيب"
        self.fields['design_style'].label = "التصميم"
        self.fields['article_count'].label = "عدد المقالات"
        self.fields['is_active'].label = "نشط"
        self.fields['category'].queryset = Category.objects.filter(is_active=True, parent__isnull=True)

HomePageCategoryFormSet = modelformset_factory(
    HomePageCategory,
    form=HomePageCategoryForm,
    extra=1,
    can_delete=True
)

from core.models import SiteSettings

class SiteSettingsForm(forms.ModelForm):
    class Meta:
        model = SiteSettings
        fields = [
            'site_name', 'logo',
            'navbar_categories', 'footer_categories',
            'footer_description',
            'facebook_url', 'twitter_url', 'instagram_url', 'youtube_url',
            'contact_email', 'contact_phone'
        ]
        widgets = {
            'site_name': forms.TextInput(attrs={'class': 'form-control'}),
            'footer_description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'facebook_url': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://facebook.com/...'}),
            'twitter_url': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://twitter.com/...'}),
            'instagram_url': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://instagram.com/...'}),
            'youtube_url': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://youtube.com/...'}),
            'contact_email': forms.EmailInput(attrs={'class': 'form-control'}),
            'contact_phone': forms.TextInput(attrs={'class': 'form-control'}),
            'navbar_categories': forms.SelectMultiple(attrs={'class': 'form-control', 'style': 'height: 150px;'}),
            'footer_categories': forms.SelectMultiple(attrs={'class': 'form-control', 'style': 'height: 150px;'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['site_name'].label = "اسم الموقع"
        self.fields['logo'].label = "شعار الموقع (Logo)"
        self.fields['navbar_categories'].label = "أقسام القائمة العلوية (Navbar)"
        self.fields['footer_categories'].label = "أقسام الفوتر (Footer)"
        self.fields['footer_description'].label = "نص نبذة الفوتر"
        self.fields['facebook_url'].label = "رابط فيسبوك"
        self.fields['twitter_url'].label = "رابط تويتر/X"
        self.fields['instagram_url'].label = "رابط إنستجرام"
        self.fields['youtube_url'].label = "رابط يوتيوب"
        self.fields['contact_email'].label = "البريد الإلكتروني للتواصل"
        self.fields['contact_phone'].label = "رقم هاتف التواصل"


