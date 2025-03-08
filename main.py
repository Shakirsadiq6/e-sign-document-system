import os
import smtplib
import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.utils import secure_filename
from PIL import Image, ImageDraw, ImageFont, ImageOps
import base64
import io
import uuid
import hashlib
from datetime import timedelta
from PyPDF2 import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
import fitz  # PyMuPDF
import tempfile
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

app = Flask(__name__)
app.secret_key = "your_secret_key"  # Change this in production

# Configuration
UPLOAD_FOLDER = 'uploads'
SIGNED_FOLDER = 'signed_documents'
ALLOWED_EXTENSIONS = {'pdf', 'docx', 'jpg', 'jpeg', 'png'}
EMAIL_SERVER = 'smtp.gmail.com'  # Change to your SMTP server
EMAIL_PORT = 587
EMAIL_USERNAME = 'noreply.aichatbot@gmail.com'  # Change to your email
EMAIL_PASSWORD = 'diqo bxuo vgmh myvh'  # Change to your password
LINK_EXPIRY_DAYS = 7  # Links expire after 7 days

# Create necessary directories
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(SIGNED_FOLDER, exist_ok=True)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['SIGNED_FOLDER'] = SIGNED_FOLDER

# Mock database for users and documents
users = {
    'user1@example.com': {'password': 'password1', 'name': 'User One'},
    'user2@example.com': {'password': 'password2', 'name': 'User Two'}
}

documents = {}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    if 'user_email' not in session:
        return redirect(url_for('login'))
    return render_template('dashboard.html', documents=documents.get(session['user_email'], []))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        if email in users and users[email]['password'] == password:
            session['user_email'] = email
            session['user_name'] = users[email]['name']
            return redirect(url_for('index'))
        else:
            flash('Invalid credentials')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_email', None)
    session.pop('user_name', None)
    return redirect(url_for('login'))

@app.route('/upload', methods=['GET', 'POST'])
def upload_document():
    if 'user_email' not in session:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        if 'document' not in request.files:
            flash('No file part')
            return redirect(request.url)
        
        file = request.files['document']
        recipient_email = request.form['recipient_email']
        
        if file.filename == '':
            flash('No selected file')
            return redirect(request.url)
        
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            
            document_id = str(uuid.uuid4())  # Generate a unique ID
            access_token = hashlib.sha256(f"{document_id}{datetime.datetime.now()}".encode()).hexdigest()[:16]
            
            document_info = {
                'id': document_id,
                'filename': filename,
                'path': file_path,
                'sender': session['user_email'],
                'recipient': recipient_email,
                'status': 'pending',
                'upload_date': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                'signed_date': None,
                'signature_positions': [],
                'access_token': access_token,
                'access_expiry': (datetime.datetime.now() + timedelta(days=LINK_EXPIRY_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
            }
            
            if recipient_email not in documents:
                documents[recipient_email] = []
            
            documents[recipient_email].append(document_info)
            
            # Debug info
            print(f"Created document: {document_info}")
            print(f"Current documents structure: {documents}")
            
            # Send email notification
            send_document_email(recipient_email, document_info)
            
            flash('Document uploaded and sent successfully')
            return redirect(url_for('index'))
    
    return render_template('upload.html')

@app.route('/view/<document_id>')
def view_document(document_id):
    # Check if user is logged in or has temporary access
    if 'user_email' not in session and 'temp_document_id' not in session:
        return redirect(url_for('login'))
    
    # Get the document
    document = None
    if 'user_email' in session:
        # Regular logged-in user access
        user_docs = documents.get(session['user_email'], [])
        document = next((doc for doc in user_docs if doc['id'] == document_id), None)
    elif 'temp_document_id' in session and session['temp_document_id'] == document_id:
        # Temporary access via direct link
        temp_email = session.get('temp_user_email')
        if temp_email and temp_email in documents:
            document = next((doc for doc in documents[temp_email] if doc['id'] == document_id), None)
        
        # If still not found, search all documents
        if not document:
            for email, docs in documents.items():
                for doc in docs:
                    if doc['id'] == document_id:
                        document = doc
                        break
                if document:
                    break
    
    if not document:
        flash('Document not found')
        if 'user_email' in session:
            return redirect(url_for('index'))
        else:
            return redirect(url_for('login'))
    
    # Verify access token for temporary access
    if 'temp_document_id' in session and not 'user_email' in session:
        if document.get('access_token') != session.get('temp_access_token'):
            session.pop('temp_document_id', None)
            session.pop('temp_user_email', None)
            session.pop('temp_access_token', None)
            flash('Invalid access token')
            return redirect(url_for('login'))
    
    # Add this at the end before returning the template
    if 'temp_document_id' in session:
        # For temporary access, ensure the sign link includes the access token
        sign_url = url_for('sign_document', document_id=document_id)
    else:
        sign_url = url_for('sign_document', document_id=document_id)
    
    return render_template('view_document.html', document=document, is_temp_access='temp_document_id' in session, sign_url=sign_url)

@app.route('/sign/<document_id>', methods=['GET', 'POST'])
def sign_document(document_id):
    print(f"Accessing sign route for document: {document_id}")
    print(f"Session data: {session}")
    
    # Check if user is logged in or has temporary access
    if 'user_email' not in session and 'temp_document_id' not in session:
        print("No user or temp access in session")
        return redirect(url_for('login'))
    
    # Get the document
    document = None
    
    # First try to find the document based on session data
    if 'user_email' in session:
        user_docs = documents.get(session['user_email'], [])
        document = next((doc for doc in user_docs if doc['id'] == document_id), None)
    elif 'temp_document_id' in session and session['temp_document_id'] == document_id:
        # For temporary access, search in all documents
        for email, docs in documents.items():
            for doc in docs:
                if doc['id'] == document_id:
                    document = doc
                    print(f"Found document via temp access: {doc}")
                    break
            if document:
                break
    
    if not document:
        print(f"Document not found: {document_id}")
        flash('Document not found')
        if 'user_email' in session:
            return redirect(url_for('index'))
        else:
            return redirect(url_for('login'))
    
    # Verify access token for temporary access
    if 'temp_access_token' in session and document.get('access_token') != session.get('temp_access_token'):
        print(f"Token mismatch: {document.get('access_token')} vs {session.get('temp_access_token')}")
        session.pop('temp_document_id', None)
        session.pop('temp_user_email', None)
        session.pop('temp_access_token', None)
        flash('Invalid access token')
        return redirect(url_for('login'))
    
    # For GET requests, prepare document preview
    if request.method == 'GET':
        # Generate a preview image for the document if it's a PDF
        preview_image = None
        if document['filename'].lower().endswith('.pdf'):
            try:
                # Create a temporary file for the preview image
                with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                    temp_preview_path = tmp.name
                
                # Open the PDF and render the first page
                pdf_document = fitz.open(document['path'])
                first_page = pdf_document[0]
                pix = first_page.get_pixmap(matrix=fitz.Matrix(2, 2))  # Scale factor for better quality
                pix.save(temp_preview_path)
                
                # Read the image and convert to base64 for embedding
                with open(temp_preview_path, 'rb') as img_file:
                    preview_image = base64.b64encode(img_file.read()).decode('utf-8')
                
                # Clean up
                os.remove(temp_preview_path)
                
            except Exception as e:
                print(f"Error generating PDF preview: {e}")
        
        return render_template('sign_document.html', 
                              document=document, 
                              is_temp_access='temp_document_id' in session,
                              preview_image=preview_image)
    
    if request.method == 'POST':
        signature_type = request.form['signature_type']
        position_x = int(request.form['position_x'])
        position_y = int(request.form['position_y'])
        
        signature_data = None
        
        if signature_type == 'draw':
            # Handle drawn signature
            signature_data = request.form['signature_data']  # Base64 encoded image
        elif signature_type == 'type':
            # Handle typed signature
            signature_text = request.form['signature_text']
            # Convert text to image (simplified)
            signature_data = f"TEXT:{signature_text}"
        elif signature_type == 'upload':
            # Handle uploaded signature image
            if 'signature_file' not in request.files:
                flash('No signature file')
                return redirect(request.url)
            
            signature_file = request.files['signature_file']
            if signature_file.filename == '':
                flash('No selected file')
                return redirect(request.url)
            
            if signature_file and allowed_file(signature_file.filename):
                # Process the signature image
                img = Image.open(signature_file)
                buffered = io.BytesIO()
                img.save(buffered, format="PNG")
                signature_data = base64.b64encode(buffered.getvalue()).decode()
        
        # After collecting signature data and before saving:
        
        # Create the SIGNED_FOLDER if it doesn't exist
        if not os.path.exists(app.config['SIGNED_FOLDER']):
            os.makedirs(app.config['SIGNED_FOLDER'])
        
        # Save the signed document with signature overlay
        signed_filename = f"signed_{document['filename']}"
        signed_path = os.path.join(app.config['SIGNED_FOLDER'], signed_filename)
        
        # Add signature to document data
        timestamp = datetime.datetime.now()
        signer_email = session.get('user_email') if 'user_email' in session else session.get('temp_user_email')
        
        signature_info = {
            'type': signature_type,
            'data': signature_data,
            'position_x': position_x,
            'position_y': position_y,
            'timestamp': timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            'signer': signer_email
        }
        
        document['signature_positions'].append(signature_info)
        document['status'] = 'signed'
        document['signed_date'] = timestamp.strftime("%Y-%m-%d %H:%M:%S")
        
        # Apply the signature to the PDF
        success = False
        
        if document['filename'].lower().endswith('.pdf'):
            try:
                print("Attempting to overlay signature with PyMuPDF")
                success = overlay_signature_on_pdf(document['path'], signed_path, [signature_info])
                print(f"PyMuPDF success: {success}")
            except Exception as e:
                print(f"PyMuPDF error: {e}")
                success = False
        
        if not success:
            # Fallback for non-PDF files or if PyMuPDF failed
            print("Using fallback copy method")
            with open(document['path'], 'rb') as src, open(signed_path, 'wb') as dst:
                dst.write(src.read())
        
        document['signed_path'] = signed_path
        
        # Notify the sender
        notify_document_signed(document)
        
        # If using temporary access, clear it after signing and redirect to thank you page
        if 'temp_document_id' in session:
            session.pop('temp_document_id', None)
            session.pop('temp_user_email', None)
            session.pop('temp_access_token', None)
            return redirect(url_for('thank_you'))
        
        flash('Document signed successfully')
        return redirect(url_for('index'))
    
    # For GET requests, render the signing page
    return render_template('sign_document.html', document=document, is_temp_access='temp_document_id' in session)

@app.route('/submit/<document_id>')
def submit_document(document_id):
    if 'user_email' not in session:
        return redirect(url_for('login'))
    
    user_docs = documents.get(session['user_email'], [])
    document = next((doc for doc in user_docs if doc['id'] == document_id), None)
    
    if not document:
        flash('Document not found')
        return redirect(url_for('index'))
    
    if document['status'] != 'signed':
        flash('Document must be signed before submission')
        return redirect(url_for('sign_document', document_id=document_id))
    
    # Mark document as submitted
    document['status'] = 'submitted'
    
    # Notify the sender
    notify_document_submitted(document)
    
    flash('Document submitted successfully')
    return redirect(url_for('index'))

@app.route('/document/<document_id>/<access_token>')
def direct_document_access(document_id, access_token):
    # Debug information
    print(f"Accessing document: {document_id} with token: {access_token}")
    print(f"Available documents: {documents}")
    
    # Find the document - search through all documents regardless of recipient
    document = None
    for email, docs in documents.items():
        for doc in docs:
            print(f"Checking doc: {doc['id']} with token: {doc.get('access_token')}")
            if doc['id'] == document_id and doc.get('access_token') == access_token:
                document = doc
                print(f"Found matching document: {document}")
                break
        if document:
            break
    
    if not document:
        print("Document not found or token mismatch")
        flash('Invalid or expired document link')
        return redirect(url_for('login'))
    
    # Check if link is expired
    try:
        expiry_date = datetime.datetime.strptime(document['access_expiry'], "%Y-%m-%d %H:%M:%S")
        if datetime.datetime.now() > expiry_date:
            print(f"Link expired. Current: {datetime.datetime.now()}, Expiry: {expiry_date}")
            flash('This document link has expired')
            return redirect(url_for('login'))
    except Exception as e:
        print(f"Error checking expiry: {e}")
        # Continue even if there's an error with expiry
    
    # Store document in session for temporary access
    session['temp_document_id'] = document_id
    session['temp_user_email'] = document['recipient']
    session['temp_access_token'] = access_token
    
    print(f"Setting session: {session}")
    
    # Directly render the document
    return render_template('view_document.html', document=document, is_temp_access=True)

@app.route('/thank-you')
def thank_you():
    return render_template('thank_you.html')

def send_document_email(recipient_email, document_info):
    """Send an email with the document for signing"""
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_USERNAME
        msg['To'] = recipient_email
        msg['Subject'] = f"Document for Signature: {document_info['filename']}"
        
        # Create direct access link - use absolute URL
        base_url = request.host_url.rstrip('/')
        direct_link = f"{base_url}/document/{document_info['id']}/{document_info['access_token']}"
        
        print(f"Generated direct link: {direct_link}")
        
        body = f"""
        Hello,
        
        You have received a document for signature from {document_info['sender']}.
        
        You can view and sign the document directly by clicking the link below:
        {direct_link}
        
        Document: {document_info['filename']}
        Uploaded on: {document_info['upload_date']}
        Link expires on: {document_info['access_expiry']}
        
        Thank you.
        """
        
        msg.attach(MIMEText(body, 'plain'))
        
        # Attach the document
        with open(document_info['path'], 'rb') as file:
            attachment = MIMEApplication(file.read(), _subtype="pdf")
            attachment.add_header('Content-Disposition', 'attachment', filename=document_info['filename'])
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

def notify_document_signed(document_info):
    """Notify the sender that the document has been signed"""
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_USERNAME
        msg['To'] = document_info['sender']
        msg['Subject'] = f"Document Signed: {document_info['filename']}"
        
        body = f"""
        Hello,
        
        The document {document_info['filename']} has been signed by {document_info['recipient']}.
        
        Signed on: {document_info['signed_date']}
        
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

def notify_document_submitted(document_info):
    """Notify the sender that the document has been submitted"""
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_USERNAME
        msg['To'] = document_info['sender']
        msg['Subject'] = f"Document Submitted: {document_info['filename']}"
        
        body = f"""
        Hello,
        
        The document {document_info['filename']} has been submitted by {document_info['recipient']}.
        
        Signed on: {document_info['signed_date']}
        Submitted on: {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        
        Thank you.
        """
        
        msg.attach(MIMEText(body, 'plain'))
        
        # Attach the signed document
        with open(document_info['signed_path'], 'rb') as file:
            attachment = MIMEApplication(file.read(), _subtype="pdf")
            attachment.add_header('Content-Disposition', 'attachment', filename=f"signed_{document_info['filename']}")
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

# Update the overlay_signature_on_pdf function to handle transparent signatures
def overlay_signature_on_pdf(input_pdf_path, output_pdf_path, signatures):
    """
    Overlay signatures on a PDF document using PyMuPDF (fitz)
    
    Args:
        input_pdf_path: Path to the original PDF
        output_pdf_path: Path to save the signed PDF
        signatures: List of signature information dictionaries
    """
    try:
        # Create a unique temporary output path to avoid permission issues
        temp_output_path = f"temp_{uuid.uuid4().hex}_{os.path.basename(output_pdf_path)}"
        
        # Open the PDF
        doc = fitz.open(input_pdf_path)
        
        # Process each signature
        for sig in signatures:
            # Get page (assuming all signatures are on first page for simplicity)
            page = doc[0]
            
            # Get page dimensions
            page_rect = page.rect
            page_width = page_rect.width
            page_height = page_rect.height
            
            # Define signature dimensions
            sig_width = 150
            sig_height = 50
            
            # Get the UI coordinates (as percentages of the container)
            ui_x_percent = sig['position_x'] / 800  # Assuming container width is 800px
            ui_y_percent = sig['position_y'] / 500  # Assuming container height is 500px
            
            # Convert to PDF coordinates - simpler approach
            # Just scale the percentages to the PDF dimensions
            pdf_x = ui_x_percent * page_width
            pdf_y = ui_y_percent * page_height
            
            # Store the exact signature position for metadata alignment
            signature_left_x = pdf_x
            
            if sig['type'] == 'draw' or sig['type'] == 'upload':
                try:
                    # Extract the base64 part if it's a data URL
                    if sig['data'].startswith('data:image'):
                        img_data = sig['data'].split(',')[1]
                    else:
                        img_data = sig['data']
                    
                    # Decode base64 to image
                    img_bytes = base64.b64decode(img_data)
                    img_buffer = io.BytesIO(img_bytes)
                    
                    # Open the image with PIL
                    with Image.open(img_buffer) as img:
                        # Convert to RGBA if not already
                        if img.mode != 'RGBA':
                            img = img.convert('RGBA')
                        
                        # Process the image to make white background transparent
                        datas = img.getdata()
                        new_data = []
                        for item in datas:
                            # If pixel is white or near-white, make it transparent
                            if item[0] > 240 and item[1] > 240 and item[2] > 240:
                                new_data.append((255, 255, 255, 0))  # Transparent
                            else:
                                new_data.append(item)  # Keep original color
                        
                        img.putdata(new_data)
                        
                        # Create a temporary file for the processed signature image
                        temp_sig_path = f"temp_sig_{uuid.uuid4().hex}.png"
                        img.save(temp_sig_path, "PNG")
                    
                    # Insert image into the PDF
                    sig_rect = fitz.Rect(pdf_x, pdf_y, pdf_x + sig_width, pdf_y + sig_height)
                    page.insert_image(sig_rect, filename=temp_sig_path)
                    
                    # Clean up
                    try:
                        os.remove(temp_sig_path)
                    except Exception as e:
                        print(f"Error removing temp signature file: {e}")
                    
                except Exception as e:
                    print(f"Error processing signature image: {e}")
                    # Fallback to text annotation if image processing fails
                    text_point = fitz.Point(pdf_x + sig_width/2, pdf_y + sig_height/2)
                    page.insert_text(text_point, "[Signature]", fontsize=12, color=(0, 0, 0))
            
            elif sig['type'] == 'type':
                # For typed signatures
                text = sig['data'].replace('TEXT:', '')
                # Position text in the center of the signature area
                text_point = fitz.Point(pdf_x + sig_width/2, pdf_y + sig_height/2)
                page.insert_text(text_point, text, fontsize=12, color=(0, 0, 0))
            
            # Add timestamp and signer info BELOW the signature
            # Use the exact same x-coordinate as the signature box
            info_point1 = fitz.Point(signature_left_x, pdf_y + sig_height + 5)  # 5 points below signature
            info_point2 = fitz.Point(signature_left_x, pdf_y + sig_height + 20)  # 20 points below signature
            
            # Add the metadata text
            page.insert_text(info_point1, f"Signed by: {sig['signer']}", fontsize=8, color=(0, 0, 0))
            page.insert_text(info_point2, f"Date: {sig['timestamp']}", fontsize=8, color=(0, 0, 0))
        
        # Save the modified PDF to the temporary path
        doc.save(temp_output_path)
        doc.close()
        
        # Copy the temporary file to the final destination instead of moving it
        with open(temp_output_path, 'rb') as src, open(output_pdf_path, 'wb') as dst:
            dst.write(src.read())
        
        # Try to remove the temporary file
        try:
            os.remove(temp_output_path)
        except Exception as e:
            print(f"Error removing temp file: {e}")
        
        return True
    except Exception as e:
        print(f"Error overlaying signature with PyMuPDF: {e}")
        # If all else fails, just copy the original file
        with open(input_pdf_path, 'rb') as src, open(output_pdf_path, 'wb') as dst:
            dst.write(src.read())
        return False

if __name__ == '__main__':
    app.run(debug=True)
