from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic import ListView, View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponseRedirect
from .models import Notification

class NotificationListView(LoginRequiredMixin, ListView):
    model = Notification
    template_name = 'notifications/notification_list.html'
    context_object_name = 'notifications'

    def get_queryset(self):
        return self.request.user.notifications.all().order_by('-created_at')

class MarkReadView(LoginRequiredMixin, View):
    def post(self, request, pk=None, *args, **kwargs):
        if pk:
            notification = get_object_or_404(Notification, pk=pk, user=request.user)
            notification.is_read = True
            notification.save(update_fields=['is_read'])
        else:
            # Mark all as read
            request.user.notifications.filter(is_read=False).update(is_read=True)
        
        next_url = request.POST.get('next') or request.GET.get('next') or 'notifications:list'
        return redirect(next_url)
