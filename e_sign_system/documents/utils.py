from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
import smtplib
import datetime
import os
import base64
import io
import uuid
import fitz
from PIL import Image
import tempfile
from django.core.files.base import ContentFile
from django.conf import settings

# Configuration
UPLOAD_FOLDER = 'uploads'
SIGNED_FOLDER = 'signed_documents'
ALLOWED_EXTENSIONS = {'pdf', 'docx', 'jpg', 'jpeg', 'png'}
EMAIL_SERVER = 'smtp.gmail.com'  # Change to your SMTP server
EMAIL_PORT = 587
EMAIL_USERNAME = 'noreply.aichatbot@gmail.com'  # Change to your email
EMAIL_PASSWORD = 'diqo bxuo vgmh myvh'  # Change to your password
LINK_EXPIRY_DAYS = 7  # Links expire after 7 days

def send_document_email(recipient_email, document):
    """Send an email with the document for signing"""
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_USERNAME
        msg['To'] = recipient_email
        msg['Subject'] = f"Document for Signature: {document.filename}"
        
        # Create direct access link - use absolute URL in Django
        base_url = 'http://localhost:8000'
        direct_link = f"{base_url}/document/{document.id}/{document.access_token}"
        
        print(f"Generated direct link: {direct_link}")
        
        body = f"""
        Hello,
        
        You have received a document for signature from {document.sender.email}.
        
        You can view and sign the document directly by clicking the link below:
        {direct_link}
        
        Document: {document.filename}
        Uploaded on: {document.upload_date}
        Link expires on: {document.access_expiry}
        
        Thank you.
        """
        
        msg.attach(MIMEText(body, 'plain'))
        
        # Attach the document
        with open(document.file.path, 'rb') as file:
            attachment = MIMEApplication(file.read(), _subtype="pdf")
            attachment.add_header('Content-Disposition', 'attachment', filename=document.filename)
            msg.attach(attachment)
        
        # Connect to server and send email
        server = smtplib.SMTP(EMAIL_SERVER, EMAIL_PORT)
        server.starttls()
        server.login(EMAIL_USERNAME, EMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
        
        return True
    except Exception as e:
        print(f"Error sending email: {e}")
        return False

def notify_document_signed(document):
    """Notify the sender that the document has been signed"""
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_USERNAME
        msg['To'] = document.sender.email
        msg['Subject'] = f"Document Signed: {document.filename}"
        
        body = f"""
        Hello,
        
        The document {document.filename} has been signed by {document.recipient_email}.
        
        Signed on: {document.signed_date}
        
        Thank you.
        """
        
        msg.attach(MIMEText(body, 'plain'))
        
        # Connect to server and send email
        server = smtplib.SMTP(EMAIL_SERVER, EMAIL_PORT)
        server.starttls()
        server.login(EMAIL_USERNAME, EMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
        
        return True
    except Exception as e:
        print(f"Error sending notification: {e}")
        return False

def notify_document_submitted(document):
    """Notify the sender that the document has been submitted"""
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_USERNAME
        msg['To'] = document.sender.email
        msg['Subject'] = f"Document Submitted: {document.filename}"
        
        body = f"""
        Hello,
        
        The document {document.filename} has been submitted by {document.recipient_email}.
        
        Signed on: {document.signed_date}
        Submitted on: {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        
        Thank you.
        """
        
        msg.attach(MIMEText(body, 'plain'))
        
        # Attach the signed document
        with open(document.signed_file.path, 'rb') as file:
            attachment = MIMEApplication(file.read(), _subtype="pdf")
            attachment.add_header('Content-Disposition', 'attachment', filename=f"signed_{document.filename}")
            msg.attach(attachment)
        
        # Connect to server and send email
        server = smtplib.SMTP(EMAIL_SERVER, EMAIL_PORT)
        server.starttls()
        server.login(EMAIL_USERNAME, EMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
        
        return True
    except Exception as e:
        print(f"Error sending notification: {e}")
        return False

def overlay_signature_on_pdf(document):
    """Apply signatures to a PDF document and save as a new PDF"""
    try:
        # Create temporary output path with PDF extension
        temp_output_path = os.path.join(settings.MEDIA_ROOT, 'temp', f"temp_{uuid.uuid4().hex}.pdf")
        os.makedirs(os.path.dirname(temp_output_path), exist_ok=True)
        
        # Open the PDF
        doc = fitz.open(document.file.path)
        
        # Process each signature
        for sig in document.signatures.all():
            page = doc[0]
            page_rect = page.rect
            
            # Calculate signature position
            sig_width = 150
            sig_height = 50
            ui_x_percent = sig.position_x / 800
            ui_y_percent = sig.position_y / 500
            pdf_x = ui_x_percent * page_rect.width
            pdf_y = ui_y_percent * page_rect.height
            
            if sig.type in ['draw', 'upload']:
                try:
                    # Process image signature
                    img_data = sig.data.split(',')[1] if sig.data.startswith('data:image') else sig.data
                    img_bytes = base64.b64decode(img_data)
                    
                    # Create temporary file for signature image
                    temp_sig_path = os.path.join(settings.MEDIA_ROOT, 'temp', f"temp_sig_{uuid.uuid4().hex}.png")
                    
                    # Process image to make white background transparent
                    with Image.open(io.BytesIO(img_bytes)) as img:
                        if img.mode != 'RGBA':
                            img = img.convert('RGBA')
                        img.save(temp_sig_path, "PNG")
                    
                    # Insert image into PDF
                    sig_rect = fitz.Rect(pdf_x, pdf_y, pdf_x + sig_width, pdf_y + sig_height)
                    page.insert_image(sig_rect, filename=temp_sig_path)
                    
                    # Clean up temporary file
                    os.remove(temp_sig_path)
                    
                except Exception as e:
                    print(f"Error processing signature image: {e}")
                    text_point = fitz.Point(pdf_x + sig_width/2, pdf_y + sig_height/2)
                    page.insert_text(text_point, "[Signature]", fontsize=12)
            
            elif sig.type == 'type':
                text = sig.data.replace('TEXT:', '')
                text_point = fitz.Point(pdf_x + sig_width/2, pdf_y + sig_height/2)
                page.insert_text(text_point, text, fontsize=12)
            
            # Add signature metadata
            info_point1 = fitz.Point(pdf_x, pdf_y + sig_height + 5)
            info_point2 = fitz.Point(pdf_x, pdf_y + sig_height + 20)
            page.insert_text(info_point1, f"Signed by: {sig.signer_email}", fontsize=8)
            page.insert_text(info_point2, f"Date: {sig.timestamp.strftime('%Y-%m-%d %H:%M:%S')}", fontsize=8)
        
        # Save the modified PDF
        doc.save(temp_output_path)
        doc.close()
        
        # Generate signed filename with proper extension
        signed_filename = document.get_signed_filename()
        
        # Save to Django's storage with proper filename
        with open(temp_output_path, 'rb') as f:
            # Force the .pdf extension in the save path
            save_path = os.path.join('signed_documents', signed_filename)
            document.signed_file.save(save_path, ContentFile(f.read()), save=True)
        
        # Clean up temporary file
        os.remove(temp_output_path)
        
        return True
    except Exception as e:
        print(f"Error overlaying signature: {e}")
        return False
