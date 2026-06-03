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
            'category', 'tags',
            'status', 'is_featured', 'is_breaking',
            'cover_image', 'allow_comments',
            'meta_title_ar', 'meta_title_en',
            'meta_desc_ar', 'meta_desc_en'
        ]
        widgets = {
            'title_ar': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'العنوان بالعربية'}),
            'title_en': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Title in English'}),
            'slug': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'slug-url'}),
            'author': forms.Select(attrs={'class': 'form-control'}),
            'body_ar': CKEditor5Widget(config_name='default', attrs={'class': 'django_ckeditor_5'}),
            'body_en': CKEditor5Widget(config_name='default', attrs={'class': 'django_ckeditor_5'}),
            'excerpt_ar': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'المقتطف بالعربية'}),
            'excerpt_en': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Excerpt in English'}),
            'category': forms.Select(attrs={'class': 'form-control'}),
            'tags': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'tag1, tag2, ...'}),
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
        self.fields['cover_image'].widget.attrs.update({'class': 'form-control'})
        self.fields['tags'].required = False

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

