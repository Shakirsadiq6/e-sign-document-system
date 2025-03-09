from django.core.files.storage import FileSystemStorage
import os

class PDFStorage(FileSystemStorage):
    def get_valid_name(self, name):
        """
        Ensure the file has a .pdf extension
        """
        name = super().get_valid_name(name)
        if not name.lower().endswith('.pdf'):
            name = f"{name}.pdf"
        return name 