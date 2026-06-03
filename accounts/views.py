from django.shortcuts import render, get_object_or_404
from django.views.generic import DetailView, ListView, UpdateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.contrib.auth.models import User
from .models import AuthorProfile, UserProfile

class AuthorDetailView(DetailView):
    model = AuthorProfile
    template_name = 'accounts/author_detail.html'
    context_object_name = 'author'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Fetch author's published articles
        context['articles'] = self.object.user.articles.filter(status='published').order_by('-published_at')
        return context

class TeamListView(ListView):
    model = AuthorProfile
    template_name = 'accounts/team_list.html'
    context_object_name = 'team_members'

    def get_queryset(self):
        return AuthorProfile.objects.filter(is_active=True)

class ProfileEditView(LoginRequiredMixin, UpdateView):
    model = UserProfile
    template_name = 'accounts/profile_edit.html'
    fields = ('avatar', 'bio', 'birth_date', 'phone_number')
    success_url = reverse_lazy('accounts:profile_edit')

    def get_object(self, queryset=None):
        profile, created = UserProfile.objects.get_or_create(user=self.request.user)
        return profile
