from modeltranslation.translator import register, TranslationOptions
from .models import SiteSettings, Advertisement, HomePageSettings

@register(SiteSettings)
class SiteSettingsTranslationOptions(TranslationOptions):
    fields = ('site_name', 'seo_title', 'seo_description')

@register(Advertisement)
class AdvertisementTranslationOptions(TranslationOptions):
    fields = ('title',)

@register(HomePageSettings)
class HomePageSettingsTranslationOptions(TranslationOptions):
    fields = ('seo_title', 'seo_description', 'seo_keywords')
