from django.shortcuts import render
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login, logout, authenticate
from django.contrib import messages
from django.core.mail import EmailMessage
from django.conf import settings
from django.utils import timezone
from django.urls import reverse
from django.http import HttpResponse
from .models import Document, Signature
from .forms import DocumentUploadForm, SignatureForm
import base64
import io
import fitz
from PIL import Image
import tempfile
import os
import uuid


def index(request):
    if not request.user.is_authenticated:
        return redirect('documents:login')
    user_documents = Document.objects.filter(
        recipient_email=request.user.email
    ) | Document.objects.filter(
        sender=request.user
    )
    return render(request, 'documents/dashboard.html', {'documents': user_documents})

def login_view(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')
        user = authenticate(request, username=email, password=password)
        
        if user is not None:
            login(request, user)
            return redirect('documents:index')
        else:
            messages.error(request, 'Invalid credentials')
    
    return render(request, 'documents/login.html')


def logout_view(request):
    logout(request)
    return redirect('documents:login')

@login_required
def upload_document(request):
    if request.method == 'POST':
        form = DocumentUploadForm(request.POST, request.FILES)
        if form.is_valid():
            document = form.save(commit=False)
            document.sender = request.user
            document.save()
            
            # Send email notification
            send_document_email(document)
            
            messages.success(request, 'Document uploaded and sent successfully')
            return redirect('documents:index')
    else:
        form = DocumentUploadForm()
    
    return render(request, 'documents/upload.html', {'form': form})

def view_document(request, document_id):
    document = get_object_or_404(Document, id=document_id)
    
    # Check permissions
    if not has_document_access(request, document):
        messages.error(request, 'Access denied')
        return redirect('documents:login')
    
    context = {
        'document': document,
        'is_temp_access': not request.user.is_authenticated,
        'sign_url': reverse('documents:sign', args=[document_id])
    }
    
    return render(request, 'documents/view_document.html', context)

def sign_document(request, document_id):
    document = get_object_or_404(Document, id=document_id)
    
    # Check permissions
    if not has_document_access(request, document):
        messages.error(request, 'Access denied')
        return redirect('documents:login')
    
    if request.method == 'POST':
        form = SignatureForm(request.POST, request.FILES)
        if form.is_valid():
            signature = form.save(commit=False)
            signature.document = document
            signature.signer_email = request.user.email if request.user.is_authenticated else document.recipient_email
            signature.save()
            
            # Update document status
            document.status = 'signed'
            document.signed_date = timezone.now()
            
            # Apply signature to PDF
            if document.file.name.lower().endswith('.pdf'):
                success = overlay_signature_on_pdf(document)
            
            document.save()
            
            # Notify sender
            notify_document_signed(document)
            
            # Clear temporary access
            if not request.user.is_authenticated:
                request.session.flush()
                return redirect('documents:thank_you')
            
            messages.success(request, 'Document signed successfully')
            return redirect('documents:index')
    else:
        form = SignatureForm()
        
        # Generate PDF preview if needed
        preview_image = None
        if document.file.name.lower().endswith('.pdf'):
            preview_image = generate_pdf_preview(document)
    
    return render(request, 'documents/sign_document.html', {
        'document': document,
        'form': form,
        'preview_image': preview_image,
        'is_temp_access': not request.user.is_authenticated
    })

@login_required
def submit_document(request, document_id):
    document = get_object_or_404(Document, id=document_id)
    
    if document.recipient_email != request.user.email:
        messages.error(request, 'Access denied')
        return redirect('documents:index')
    
    if document.status != 'signed':
        messages.error(request, 'Document must be signed before submission')
        return redirect('documents:sign', document_id=document_id)
    
    document.status = 'submitted'
    document.save()
    
    # Notify sender
    notify_document_submitted(document)
    
    messages.success(request, 'Document submitted successfully')
    return redirect('documents:index')

def direct_document_access(request, document_id, access_token):
    document = get_object_or_404(Document, id=document_id, access_token=access_token)
    
    # Check if link is expired
    if timezone.now() > document.access_expiry:
        messages.error(request, 'This document link has expired')
        return redirect('documents:login')
    
    # Store document access in session
    request.session['temp_document_id'] = str(document.id)
    request.session['temp_user_email'] = document.recipient_email
    request.session['temp_access_token'] = document.access_token
    
    return render(request, 'documents/view_document.html', {
        'document': document,
        'is_temp_access': True
    })

def thank_you(request):
    return render(request, 'documents/thank_you.html')

# Helper functions
def has_document_access(request, document):
    """Check if the current user/session has access to the document"""
    if request.user.is_authenticated:
        return (document.sender == request.user or 
                document.recipient_email == request.user.email)
    else:
        return (request.session.get('temp_document_id') == str(document.id) and
                request.session.get('temp_access_token') == document.access_token)

def generate_pdf_preview(document):
    """Generate a preview image for a PDF document"""
    try:
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
            temp_preview_path = tmp.name
        
        pdf_document = fitz.open(document.file.path)
        first_page = pdf_document[0]
        pix = first_page.get_pixmap(matrix=fitz.Matrix(2, 2))
        pix.save(temp_preview_path)
        
        with open(temp_preview_path, 'rb') as img_file:
            preview_image = base64.b64encode(img_file.read()).decode('utf-8')
        
        os.remove(temp_preview_path)
        return preview_image
    except Exception as e:
        print(f"Error generating PDF preview: {e}")
        return None

def overlay_signature_on_pdf(document):
    """Apply signatures to a PDF document"""
    try:
        # Create temporary output path
        temp_output_path = f"temp_{uuid.uuid4().hex}_{os.path.basename(document.file.name)}"
        
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
                # Process image signature
                img_data = sig.data.split(',')[1] if sig.data.startswith('data:image') else sig.data
                img_bytes = base64.b64decode(img_data)
                
                with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                    temp_sig_path = tmp.name
                    
                    # Process image to make white background transparent
                    with Image.open(io.BytesIO(img_bytes)) as img:
                        if img.mode != 'RGBA':
                            img = img.convert('RGBA')
                        img.save(temp_sig_path, "PNG")
                
                # Insert image into PDF
                sig_rect = fitz.Rect(pdf_x, pdf_y, pdf_x + sig_width, pdf_y + sig_height)
                page.insert_image(sig_rect, filename=temp_sig_path)
                os.remove(temp_sig_path)
            
            elif sig.type == 'type':
                # Insert typed signature
                text = sig.data.replace('TEXT:', '')
                text_point = fitz.Point(pdf_x + sig_width/2, pdf_y + sig_height/2)
                page.insert_text(text_point, text, fontsize=12, color=(0, 0, 0))
            
            # Add signature metadata
            info_point1 = fitz.Point(pdf_x, pdf_y + sig_height + 5)
            info_point2 = fitz.Point(pdf_x, pdf_y + sig_height + 20)
            page.insert_text(info_point1, f"Signed by: {sig.signer_email}", fontsize=8)
            page.insert_text(info_point2, f"Date: {sig.timestamp.strftime('%Y-%m-%d %H:%M:%S')}", fontsize=8)
        
        # Save the modified PDF
        doc.save(temp_output_path)
        doc.close()
        
        # Update document's signed file
        with open(temp_output_path, 'rb') as f:
            document.signed_file.save(
                f"signed_{document.filename}",
                ContentFile(f.read()),
                save=True
            )
        
        os.remove(temp_output_path)
        return True
    except Exception as e:
        print(f"Error overlaying signature: {e}")
        return False