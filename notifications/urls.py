from django.urls import path
from .views import NotificationListView, MarkReadView

app_name = 'notifications'

urlpatterns = [
    path('', NotificationListView.as_view(), name='list'),
    path('mark-read/', MarkReadView.as_view(), name='mark_all_read'),
    path('mark-read/<int:pk>/', MarkReadView.as_view(), name='mark_read'),
]
