from modeltranslation.translator import register, TranslationOptions
from .models import AuthorProfile

@register(AuthorProfile)
class AuthorProfileTranslationOptions(TranslationOptions):
    fields = ('display_name', 'bio')
