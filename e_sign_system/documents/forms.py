from django import forms
from .models import Document, Signature

class DocumentUploadForm(forms.ModelForm):
    class Meta:
        model = Document
        fields = ['file', 'recipient_email']
        
    def clean_file(self):
        file = self.cleaned_data['file']
        ext = file.name.split('.')[-1].lower()
        if ext not in ['pdf', 'docx', 'jpg', 'jpeg', 'png']:
            raise forms.ValidationError('Unsupported file type')
        return file

class SignatureForm(forms.ModelForm):
    class Meta:
        model = Signature
        fields = ['type', 'data', 'position_x', 'position_y']
        widgets = {
            'position_x': forms.HiddenInput(),
            'position_y': forms.HiddenInput(),
        }