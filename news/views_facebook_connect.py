"""
Public, staff-free "Connect Facebook Page" OAuth flow.

Staff generate a signed one-time-ish link for a given WordPressSite (see
`make_facebook_connect_token` / the copy-link button in wp_site_form.html,
and the equivalent field surfaced inside the WordPress plugin's settings
page). The client clicks that link, authorizes our Facebook App, picks
their Page if they manage more than one, and we store the resulting
Page ID + long-lived Page Access Token directly on the WordPressSite row.

Security model: there is no login here (the client has no account on this
system at all - see StaffRequiredMixin gating the rest of /ai-dashboard/).
Instead, the link itself is a Django `signing.dumps()` token binding a
specific WordPressSite id, so only someone holding a link we generated can
act, and only for that one site. The feature toggle (`social_image_enabled`)
and the credentials this flow fills in remain invisible/uneditable to the
client anywhere else in the system.
"""
import logging
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.core import signing
from django.core.signing import BadSignature, SignatureExpired
from django.shortcuts import render, get_object_or_404
from django.urls import reverse
from django.views import View

from .models import WordPressSite

logger = logging.getLogger(__name__)

FACEBOOK_CONNECT_SALT = 'facebook-connect'
FACEBOOK_CONNECT_MAX_AGE = 60 * 60 * 24 * 30  # link stays clickable for 30 days
FACEBOOK_GRAPH_VERSION = 'v19.0'
FACEBOOK_OAUTH_SCOPES = 'pages_show_list,pages_read_engagement,pages_manage_posts'


def make_facebook_connect_token(wp_site_id):
    """Build the signed token embedded in the client-facing connect link."""
    return signing.dumps(wp_site_id, salt=FACEBOOK_CONNECT_SALT)


def _resolve_site_from_token(token):
    site_id = signing.loads(token, salt=FACEBOOK_CONNECT_SALT, max_age=FACEBOOK_CONNECT_MAX_AGE)
    return get_object_or_404(WordPressSite, pk=site_id)


class FacebookConnectStartView(View):
    def get(self, request, token):
        if not settings.FACEBOOK_APP_ID:
            return render(request, 'facebook_connect/error.html', {
                'message': 'ميزة ربط فيسبوك غير مفعّلة على الخادم حالياً. برجاء التواصل معنا.',
            }, status=500)
        try:
            wp_site = _resolve_site_from_token(token)
        except SignatureExpired:
            return render(request, 'facebook_connect/error.html', {
                'message': 'انتهت صلاحية هذا الرابط. برجاء طلب رابط جديد من فريق الدعم.',
            }, status=400)
        except BadSignature:
            return render(request, 'facebook_connect/error.html', {
                'message': 'هذا الرابط غير صالح.',
            }, status=400)

        redirect_uri = request.build_absolute_uri(reverse('facebook_connect_callback'))
        params = {
            'client_id': settings.FACEBOOK_APP_ID,
            'redirect_uri': redirect_uri,
            'state': token,
            'scope': FACEBOOK_OAUTH_SCOPES,
            'response_type': 'code',
        }
        oauth_url = f'https://www.facebook.com/{FACEBOOK_GRAPH_VERSION}/dialog/oauth?{urlencode(params)}'
        return render(request, 'facebook_connect/start.html', {
            'wp_site': wp_site,
            'oauth_url': oauth_url,
        })


class FacebookConnectCallbackView(View):
    def get(self, request):
        fb_error = request.GET.get('error')
        if fb_error:
            error_desc = request.GET.get('error_description', '')
            return render(request, 'facebook_connect/error.html', {
                'message': f'تم إلغاء عملية الربط أو رفض الصلاحيات المطلوبة: {error_desc or fb_error}',
            })

        token = request.GET.get('state', '')
        code = request.GET.get('code', '')
        try:
            wp_site = _resolve_site_from_token(token)
        except (SignatureExpired, BadSignature):
            return render(request, 'facebook_connect/error.html', {
                'message': 'انتهت صلاحية الجلسة أو الرابط غير صالح. برجاء إعادة المحاولة من الرابط الأصلي.',
            })
        if not code:
            return render(request, 'facebook_connect/error.html', {
                'message': 'لم يتم استلام رمز التفويض من فيسبوك.',
            })

        redirect_uri = request.build_absolute_uri(reverse('facebook_connect_callback'))

        try:
            resp = requests.get(
                f'https://graph.facebook.com/{FACEBOOK_GRAPH_VERSION}/oauth/access_token',
                params={
                    'client_id': settings.FACEBOOK_APP_ID,
                    'client_secret': settings.FACEBOOK_APP_SECRET,
                    'redirect_uri': redirect_uri,
                    'code': code,
                },
                timeout=15,
            )
            resp.raise_for_status()
            short_token = resp.json()['access_token']

            resp2 = requests.get(
                f'https://graph.facebook.com/{FACEBOOK_GRAPH_VERSION}/oauth/access_token',
                params={
                    'grant_type': 'fb_exchange_token',
                    'client_id': settings.FACEBOOK_APP_ID,
                    'client_secret': settings.FACEBOOK_APP_SECRET,
                    'fb_exchange_token': short_token,
                },
                timeout=15,
            )
            resp2.raise_for_status()
            long_user_token = resp2.json()['access_token']

            resp3 = requests.get(
                f'https://graph.facebook.com/{FACEBOOK_GRAPH_VERSION}/me/accounts',
                params={'access_token': long_user_token, 'fields': 'id,name,access_token,category'},
                timeout=15,
            )
            resp3.raise_for_status()
            pages = resp3.json().get('data', [])
        except requests.RequestException as e:
            logger.error(f"Facebook OAuth exchange failed for wp_site {wp_site.id}: {e}")
            return render(request, 'facebook_connect/error.html', {
                'message': 'حدث خطأ أثناء التواصل مع فيسبوك. برجاء المحاولة مرة أخرى لاحقاً.',
            })

        if not pages:
            return render(request, 'facebook_connect/error.html', {
                'message': 'لم يتم العثور على أي صفحة فيسبوك تديرها بهذا الحساب. تأكد أنك مسؤول (Admin) على صفحة الفيسبوك أولاً ثم أعد المحاولة.',
            })

        if len(pages) == 1:
            page = pages[0]
            wp_site.facebook_page_id = page['id']
            wp_site.facebook_access_token = page['access_token']
            wp_site.save(update_fields=['facebook_page_id', 'facebook_access_token'])
            return render(request, 'facebook_connect/success.html', {
                'wp_site': wp_site,
                'page_name': page.get('name', ''),
            })

        request.session[f'fb_connect_pages_{wp_site.id}'] = pages
        return render(request, 'facebook_connect/select_page.html', {
            'wp_site': wp_site,
            'pages': pages,
            'token': token,
        })


class FacebookConnectSelectPageView(View):
    def post(self, request, token):
        try:
            wp_site = _resolve_site_from_token(token)
        except (SignatureExpired, BadSignature):
            return render(request, 'facebook_connect/error.html', {
                'message': 'انتهت صلاحية الجلسة. برجاء إعادة المحاولة من الرابط الأصلي.',
            })

        pages = request.session.get(f'fb_connect_pages_{wp_site.id}', [])
        page_id = request.POST.get('page_id')
        page = next((p for p in pages if p['id'] == page_id), None)
        if not page:
            return render(request, 'facebook_connect/error.html', {
                'message': 'اختيار غير صالح، برجاء إعادة المحاولة من الرابط الأصلي.',
            })

        wp_site.facebook_page_id = page['id']
        wp_site.facebook_access_token = page['access_token']
        wp_site.save(update_fields=['facebook_page_id', 'facebook_access_token'])
        request.session.pop(f'fb_connect_pages_{wp_site.id}', None)
        return render(request, 'facebook_connect/success.html', {
            'wp_site': wp_site,
            'page_name': page.get('name', ''),
        })
