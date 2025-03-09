from django.db import models
from django.contrib.auth.models import User
import uuid
from django.utils import timezone
from datetime import timedelta
import os
from .storage import PDFStorage

class Document(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    filename = models.CharField(max_length=255)
    file = models.FileField(upload_to='documents/')
    signed_file = models.FileField(
        upload_to='signed_documents/',
        storage=PDFStorage(),
        null=True,
        blank=True
    )
    sender = models.ForeignKey(User, on_delete=models.CASCADE)
    recipient_email = models.EmailField()
    status = models.CharField(max_length=20, choices=[
        ('pending', 'Pending'),
        ('signed', 'Signed'),
        ('submitted', 'Submitted')
    ], default='pending')
    upload_date = models.DateTimeField(auto_now_add=True)
    signed_date = models.DateTimeField(null=True, blank=True)
    access_token = models.CharField(max_length=100, unique=True)
    access_expiry = models.DateTimeField()

    def save(self, *args, **kwargs):
        # Ensure original filename is preserved
        if not self.pk and self.file:  # Only on creation
            self.filename = self.file.name
        if not self.access_token:
            self.access_token = uuid.uuid4().hex[:100]
            self.access_expiry = timezone.now() + timedelta(days=7)
        super().save(*args, **kwargs)

    def get_signed_filename(self):
        """Generate filename for signed document"""
        base_name = os.path.splitext(self.filename)[0]
        return f"signed_{base_name}.pdf"

class Signature(models.Model):
    document = models.ForeignKey(Document, related_name='signatures', on_delete=models.CASCADE)
    signer_email = models.EmailField()
    type = models.CharField(max_length=20)  # 'draw', 'type', or 'upload'
    data = models.TextField()  # Base64 image data or text
    position_x = models.IntegerField()
    position_y = models.IntegerField()
    timestamp = models.DateTimeField(auto_now_add=True)
