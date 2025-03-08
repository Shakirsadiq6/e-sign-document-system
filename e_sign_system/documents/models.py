from django.db import models
from django.contrib.auth.models import User
import uuid
from django.utils import timezone
from datetime import timedelta

class Document(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    filename = models.CharField(max_length=255)
    file = models.FileField(upload_to='uploads/')
    signed_file = models.FileField(upload_to='signed_documents/', null=True, blank=True)
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_documents')
    recipient_email = models.EmailField()
    status = models.CharField(max_length=20, choices=[
        ('pending', 'Pending'),
        ('signed', 'Signed'),
        ('submitted', 'Submitted')
    ], default='pending')
    upload_date = models.DateTimeField(auto_now_add=True)
    signed_date = models.DateTimeField(null=True, blank=True)
    access_token = models.CharField(max_length=16)
    access_expiry = models.DateTimeField()

    def save(self, *args, **kwargs):
        if not self.access_token:
            self.access_token = uuid.uuid4().hex[:16]
            self.access_expiry = timezone.now() + timedelta(days=7)
        super().save(*args, **kwargs)

class Signature(models.Model):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name='signatures')
    type = models.CharField(max_length=20)
    data = models.TextField()
    position_x = models.IntegerField()
    position_y = models.IntegerField()
    timestamp = models.DateTimeField(auto_now_add=True)
    signer_email = models.EmailField()
