from modeltranslation.translator import register, TranslationOptions
from .models import Category, Tag, Article

@register(Category)
class CategoryTranslationOptions(TranslationOptions):
    fields = ('name', 'meta_title', 'meta_description', 'meta_keywords')

@register(Tag)
class TagTranslationOptions(TranslationOptions):
    fields = ('name',)

@register(Article)
class ArticleTranslationOptions(TranslationOptions):
    fields = ('title', 'body', 'excerpt', 'meta_title', 'meta_desc')
