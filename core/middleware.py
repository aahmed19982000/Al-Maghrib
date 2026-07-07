from django.conf import settings

class SubdomainRoutingMiddleware:
    """
    Middleware that checks the incoming host name.
    If it starts with the 'ai' subdomain (e.g. ai.almaghrib.com or ai.localhost),
    it overrides the request's urlconf to route to the AI control panel views.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = request.get_host().split(':')[0].lower()
        parts = host.split('.')
        
        # Check if the first part of the domain is 'ai'
        if len(parts) >= 2 and parts[0] == 'ai':
            request.urlconf = 'almaghrib.urls_ai'
            
        response = self.get_response(request)
        return response
