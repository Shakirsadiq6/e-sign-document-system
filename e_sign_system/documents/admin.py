from django.contrib import admin

# Register your models here.
from .models import Document, Signature

admin.site.register(Document)
admin.site.register(Signature)

