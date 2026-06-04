from django import forms
from accounts.models import AuthorProfile, AuthorExpertise
from django.forms import inlineformset_factory

class AuthorProfileForm(forms.ModelForm):
    class Meta:
        model = AuthorProfile
        fields = [
            'display_name', 'bio', 'avatar', 'role', 
            'twitter', 'linkedin', 'email_public', 
            'specialization', 'is_active',
            'can_publish_directly', 'can_edit_others', 'can_delete_articles'
        ]
        widgets = {
            'display_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Display Name'}),
            'bio': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Short biography...'}),
            'role': forms.Select(attrs={'class': 'form-control'}),
            'twitter': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://twitter.com/username'}),
            'linkedin': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://linkedin.com/in/username'}),
            'email_public': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'public@example.com'}),
            'specialization': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Specialization'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['display_name'].label = "الاسم التعريفي (Display Name)"
        self.fields['bio'].label = "السيرة الذاتية (Bio)"
        self.fields['avatar'].label = "الصورة الشخصية (Avatar)"
        self.fields['role'].label = "الدور في الموقع (Role)"
        self.fields['twitter'].label = "رابط حساب Twitter"
        self.fields['linkedin'].label = "رابط حساب LinkedIn"
        self.fields['email_public'].label = "البريد الإلكتروني العام"
        self.fields['specialization'].label = "التخصص العلمي/الصحفي"
        self.fields['is_active'].label = "الحساب نشط (Active)"
        self.fields['can_publish_directly'].label = "صلاحية النشر المباشر دون مراجعة"
        self.fields['can_edit_others'].label = "صلاحية تعديل مقالات الكتاب الآخرين"
        self.fields['can_delete_articles'].label = "صلاحية حذف المقالات (حذف مؤقت)"
        
        for field_name in ['is_active', 'can_publish_directly', 'can_edit_others', 'can_delete_articles']:
            self.fields[field_name].required = False

class AuthorExpertiseForm(forms.ModelForm):
    class Meta:
        model = AuthorExpertise
        fields = ['title', 'description', 'icon']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'مثال: التحليل الإقليمي'}),
            'description': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'مثال: السياسات والشؤون المغاربية'}),
            'icon': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'account_balance'}),
        }

AuthorExpertiseFormSet = inlineformset_factory(
    AuthorProfile,
    AuthorExpertise,
    form=AuthorExpertiseForm,
    extra=1,
    can_delete=True
)

from django.contrib.auth.models import User

class AuthorCreateForm(forms.ModelForm):
    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'username'}),
        label="اسم المستخدم (Username)"
    )
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'email@example.com'}),
        label="البريد الإلكتروني للقروب/الدخول"
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': '••••••••'}),
        label="كلمة المرور"
    )
    first_name = forms.CharField(
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'First Name'}),
        label="الاسم الأول"
    )
    last_name = forms.CharField(
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Last Name'}),
        label="الاسم الأخير"
    )

    class Meta:
        model = AuthorProfile
        fields = [
            'display_name', 'bio', 'avatar', 'role', 
            'twitter', 'linkedin', 'email_public', 
            'specialization', 'is_active',
            'can_publish_directly', 'can_edit_others', 'can_delete_articles'
        ]
        widgets = {
            'display_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Display Name'}),
            'bio': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Short biography...'}),
            'role': forms.Select(attrs={'class': 'form-control'}),
            'twitter': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://twitter.com/username'}),
            'linkedin': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://linkedin.com/in/username'}),
            'email_public': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'public@example.com'}),
            'specialization': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Specialization'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['display_name'].label = "الاسم التعريفي (Display Name)"
        self.fields['bio'].label = "السيرة الذاتية (Bio)"
        self.fields['avatar'].label = "الصورة الشخصية (Avatar)"
        self.fields['role'].label = "الدور في الموقع (Role)"
        self.fields['twitter'].label = "رابط حساب Twitter"
        self.fields['linkedin'].label = "رابط حساب LinkedIn"
        self.fields['email_public'].label = "البريد الإلكتروني العام للجمهور"
        self.fields['specialization'].label = "التخصص العلمي/الصحفي"
        self.fields['is_active'].label = "الحساب نشط (Active)"
        self.fields['can_publish_directly'].label = "صلاحية النشر المباشر دون مراجعة"
        self.fields['can_edit_others'].label = "صلاحية تعديل مقالات الكتاب الآخرين"
        self.fields['can_delete_articles'].label = "صلاحية حذف المقالات (حذف مؤقت)"
        
        for field_name in ['is_active', 'can_publish_directly', 'can_edit_others', 'can_delete_articles']:
            self.fields[field_name].required = False

    def clean_username(self):
        username = self.cleaned_data.get('username')
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError("اسم المستخدم هذا مستخدم بالفعل.")
        return username

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("البريد الإلكتروني هذا مسجل بالفعل.")
        return email

    def save(self, commit=True):
        username = self.cleaned_data.get('username')
        email = self.cleaned_data.get('email')
        password = self.cleaned_data.get('password')
        first_name = self.cleaned_data.get('first_name', '')
        last_name = self.cleaned_data.get('last_name', '')

        # Create Django User
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name
        )
        
        # Set is_staff to True if role is admin or editor (so they can access admin or staff views if needed)
        role = self.cleaned_data.get('role')
        if role in ['admin', 'editor']:
            user.is_staff = True
            user.save()

        # Create AuthorProfile
        author_profile = super().save(commit=False)
        author_profile.user = user
        if commit:
            author_profile.save()
        return author_profile

