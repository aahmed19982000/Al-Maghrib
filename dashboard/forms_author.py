from django import forms
from accounts.models import AuthorProfile

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
