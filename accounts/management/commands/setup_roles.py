from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from news.models import Article, Category, Comment

class Command(BaseCommand):
    help = "Initializes default roles (Groups) and their permissions"

    def handle(self, *args, **options):
        # 1. Create Groups
        super_admin, _ = Group.objects.get_or_create(name='SuperAdmin')
        editor, _ = Group.objects.get_or_create(name='Editor')
        author, _ = Group.objects.get_or_create(name='Author')
        moderator, _ = Group.objects.get_or_create(name='Moderator')

        # Get Content Types
        article_ct = ContentType.objects.get_for_model(Article)
        category_ct = ContentType.objects.get_for_model(Category)
        comment_ct = ContentType.objects.get_for_model(Comment)
        
        # Clear existing permissions to avoid duplicate issues on re-run
        super_admin.permissions.clear()
        editor.permissions.clear()
        author.permissions.clear()
        moderator.permissions.clear()

        # Fetch all permissions for news app
        article_perms = Permission.objects.filter(content_type=article_ct)
        category_perms = Permission.objects.filter(content_type=category_ct)
        comment_perms = Permission.objects.filter(content_type=comment_ct)

        # 2. SuperAdmin Permissions: ALL perms for Article, Category, Comment
        for perm in list(article_perms) + list(category_perms) + list(comment_perms):
            super_admin.permissions.add(perm)

        # 3. Editor Permissions
        editor_perms = [
            'add_article', 'change_article', 'view_article', 'delete_article', 'can_publish', 'can_feature',
            'add_category', 'change_category', 'view_category',
            'add_comment', 'change_comment', 'view_comment', 'delete_comment'
        ]
        for codename in editor_perms:
            try:
                perm = Permission.objects.get(codename=codename, content_type__in=[article_ct, category_ct, comment_ct])
                editor.permissions.add(perm)
            except Permission.DoesNotExist:
                self.stdout.write(self.style.WARNING(f"Permission '{codename}' not found"))

        # 4. Author Permissions
        try:
            author.permissions.add(Permission.objects.get(codename='add_article', content_type=article_ct))
            author.permissions.add(Permission.objects.get(codename='view_article', content_type=article_ct))
        except Permission.DoesNotExist:
            pass

        # 5. Moderator Permissions
        mod_perms = ['view_article', 'view_comment', 'change_comment', 'delete_comment']
        for codename in mod_perms:
            try:
                perm = Permission.objects.get(codename=codename, content_type__in=[article_ct, comment_ct])
                moderator.permissions.add(perm)
            except Permission.DoesNotExist:
                pass

        # 6. Assign object-level permissions for all existing articles to their authors
        from guardian.shortcuts import assign_perm
        articles_count = 0
        for article in Article.all_objects.all():
            assign_perm('change_article', article.author, article)
            assign_perm('delete_article', article.author, article)
            articles_count += 1
            
        self.stdout.write(self.style.SUCCESS(f"Assigned object-level permissions for {articles_count} articles to their authors."))
        self.stdout.write(self.style.SUCCESS("Successfully created roles and assigned default permissions!"))
