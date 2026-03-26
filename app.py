import os
from flask import Flask, render_template, request, redirect, url_for, session
from supabase import create_client, Client
from dotenv import load_dotenv
import urllib.parse
from werkzeug.utils import secure_filename
from flask_cors import CORS 
from datetime import datetime
import smtplib
from email.message import EmailMessage
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta

# --- MAIL CONFIG & FUNCTION ---
SENDER_EMAIL = "sb.bhavani.sb@gmail.com"
APP_PASSWORD = "bxyj mvyy laxu sawt" # Google App Password
load_dotenv()

def send_expiry_alert(receiver_email, filename):
    msg = EmailMessage()
    msg['Subject'] = "Media Vault: File Expiry Alert! ⚠️"
    msg['From'] = SENDER_EMAIL
    msg['To'] = receiver_email
    
    body = f"Hii,\n\nThe file '{filename}' shared with you is about to expire (75% time completed). Please download it soon!\n\nTeam Media Vault"
    msg.set_content(body)

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(SENDER_EMAIL, APP_PASSWORD)
            smtp.send_message(msg)
            print(f"Alert mail sent to {receiver_email}")
    except Exception as e:
        print(f"Mail Error: {e}")

# Scheduler start pannunga
scheduler = BackgroundScheduler()
scheduler.start()

app = Flask(__name__)
CORS(app)
app.secret_key = "230525"

# Supabase Credentials
url = "https://wpawraxihaynnuikhxqi.supabase.co"
key = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6IndwYXdyYXhpaGF5bm51aWtoeHFpIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Njg1NTQyOTIsImV4cCI6MjA4NDEzMDI5Mn0.22ZIHmLr01r8VZNxs0B1QYy3C_a1f3o27kAD-CA7T8s"

supabase: Client = create_client(url, key)

# --- HELPER FUNCTIONS ---
def get_current_user_email():
    return session.get('user_email')

def get_storage_usage(user_id):
    try:
        # 1. Fetch data
        res = supabase.table("file_metadata") \
            .select("file_size") \
            .eq("user_id", user_id) \
            .eq("is_deleted", False) \
            .execute()

        print(f"DEBUG: Found {len(res.data)} files for user {user_id}")

        if not res.data:
            return 0

        # 2. Convert to int and sum (Safe way)
        total_bytes = 0
        for item in res.data:
            try:
                # Oru velai value string-ah iruntha int-ah mathirum
                size = int(item.get('file_size', 0) or 0)
                total_bytes += size
            except:
                continue

        # 3. Calculation
        total_mb = round(total_bytes / (1024 * 1024), 2)
        print(f"DEBUG: Total MB calculated: {total_mb}")
        
        return total_mb

    except Exception as e:
        print(f"CRITICAL ERROR: {e}")
        return 0

def log_activity(user_id, action, details):
    """Inserts a record into activity_logs table"""
    try:
        supabase.table("activity_logs").insert({
            "user_id": user_id,
            "action": action,
            "details": details
        }).execute()
    except Exception as e:
        print(f"Logging Error: {e}")

# --- ROUTES ---
def get_breadcrumbs(folder_id):
    breadcrumbs = []
    curr_id = folder_id
    while curr_id:
        res = supabase.table("folders").select("id, name, parent_id").eq("id", curr_id).single().execute()
        if res.data:
            breadcrumbs.insert(0, res.data)
            curr_id = res.data['parent_id']
        else:
            break
    return breadcrumbs

@app.route('/')
@app.route('/folder/<int:folder_id>')
def index(folder_id=None):
    if 'user_id' not in session: 
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    usage = get_storage_usage(user_id)
    quota = 100 
    
    # Initialize defaults to prevent UnboundLocalError
    current_folder_name = ""
    breadcrumbs = []

    # Fetch Folders
    folder_query = supabase.table("folders").select("*").eq("user_id", user_id)
    if folder_id:
        folder_query = folder_query.eq("parent_id", folder_id)
    else:
        folder_query = folder_query.is_("parent_id", "null")
    folders_list = folder_query.execute().data

    # Fetch Files
    file_query = supabase.table("file_metadata").select("*").eq("user_id", user_id).eq("is_deleted", False)
    if folder_id:
        file_query = file_query.eq("folder_id", folder_id)
    else:
        file_query = file_query.is_("folder_id", "null")
    files_list = file_query.execute().data

    # Handle Folder-Specific Metadata and Breadcrumbs
    if folder_id:
        try:
            folder_data = supabase.table("folders").select("name").eq("id", folder_id).single().execute()
            if folder_data.data:
                current_folder_name = folder_data.data['name']
            
            # This call now safely updates the empty list defined above
            breadcrumbs = get_breadcrumbs(folder_id)
        except Exception as e:
            print(f"Error fetching folder metadata: {e}")
            # Optional: handle case where folder_id doesn't exist in DB

    user_email = session.get('user_email')
    profile_pic = None
    
    if user_email:
        # Database-la irunthu profile pic URL-ah edukkirom
        user_res = supabase.table('users').select("profile_pic_url").eq("email", user_email).execute()
        if user_res.data:
            profile_pic = user_res.data[0].get('profile_pic_url')
            
   
    return render_template(
        'index.html', 
        folders=folders_list, 
        files=files_list, 
        current_folder_id=folder_id,
        current_folder_name=current_folder_name,
        breadcrumbs=breadcrumbs,
        usage=usage,
        quota=quota,
        profile_pic=profile_pic
    )

storage = supabase.storage  
@app.route('/profile', methods=['GET', 'POST'])
def profile_page():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    user_email = session.get('user_email')
    message = None

    # --- 1. POST Request: Handle Username & Password Updates ---
    if request.method == 'POST':
        new_username = request.form.get('username')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')

        try:
            # Username Update Logic
            if new_username:
                # Password hash illama verum username & email mattum upsert pannuvom
                supabase.table('users').upsert({
                    "email": user_email,
                    "username": new_username
                }, on_conflict="email").execute()
                message = "Username updated successfully!"

            # Password Update Logic (Using Supabase Auth directly)
            if new_password:
                if new_password == confirm_password:
                    # Namma users table-la password hash store panna matton (Security + avoid null error)
                    supabase.auth.update_user({"password": new_password})
                    message = "Profile and Password updated successfully!"
                else:
                    message = "Passwords do not match!"
                    
        except Exception as e:
            # Detailed error logging
            print(f"Update Error: {e}")
            message = f"Error: {str(e)}"

    # --- 2. Fetch User Data (Username & Profile Pic) ---
    profile_pic = None
    # Fallback to email prefix if username not set
    username = user_email.split('@')[0] if user_email else "User"
    
    try:
        user_res = supabase.table('users').select("username, profile_pic_url").eq("email", user_email).execute()
        if user_res.data:
            username = user_res.data[0].get('username', username)
            profile_pic = user_res.data[0].get('profile_pic_url')
    except Exception as e:
        print(f"DB Fetch Error: {e}")

    # --- 3. Storage Breakdown Logic (Keep your existing logic) ---
    img_pct, vid_pct, doc_pct = 0, 0, 0
    quota_mb = 100
    quota_bytes = quota_mb * 1024 * 1024

    try:
        response = supabase.table('file_metadata').select("file_size, file_name").eq("user_id", user_id).eq("is_deleted", False).execute()
        files = response.data if response.data else []
        
        img_size = sum(f['file_size'] for f in files if f['file_name'].lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')))
        vid_size = sum(f['file_size'] for f in files if f['file_name'].lower().endswith(('.mp4', '.mov', '.avi', '.mkv')))
        doc_size = sum(f['file_size'] for f in files if f['file_name'].lower().endswith(('.pdf', '.doc', '.docx', '.txt', '.zip')))

        if quota_bytes > 0:
            img_pct = (img_size / quota_bytes) * 100
            vid_pct = (vid_size / quota_bytes) * 100
            doc_pct = (doc_size / quota_bytes) * 100
    except Exception as e:
        print(f"Storage Breakdown Error: {e}")

    usage = get_storage_usage(user_id)

    return render_template('profile.html', 
                           user_email=user_email, 
                           username=username,
                           profile_pic=profile_pic,
                           usage=usage, 
                           quota=quota_mb, 
                           img_pct=img_pct, 
                           vid_pct=vid_pct, 
                           doc_pct=doc_pct,
                           message=message)

# --- 4. Profile Picture Upload Route ---
@app.route('/update_profile_pic', methods=['POST'])
def update_profile_pic():
    if 'avatar' not in request.files:
        return {"error": "No file"}, 400
    
    file = request.files['avatar']
    user_email = session.get('user_email')
    
    try:
        file_ext = file.filename.rsplit('.', 1)[1].lower()
        file_path = f"avatars/{user_email}.{file_ext}"
        bucket_name = "files" # Unga storage bucket name
        
        # Upload to Supabase Storage
        file_content = file.read()
        supabase.storage.from_(bucket_name).upload(
            path=file_path,
            file=file_content,
            file_options={"content-type": file.content_type, "x-upsert": "true"}
        )
        
        public_url = supabase.storage.from_(bucket_name).get_public_url(file_path)
        
        # Save URL to users table
        supabase.table('users').upsert({
            "email": user_email,
            "profile_pic_url": public_url
        }, on_conflict="email").execute()
        
        return {"url": public_url}, 200
    except Exception as e:
        return {"error": str(e)}, 500

@app.context_processor # Ithu use panna ella page-layum intha data kedaikkum
def inject_storage_breakdown():
    user_email = session.get('user_email')
    # SQL query to get files by type
    # Example: Select mime_type, sum(file_size) from files where user_email = ... group by mime_type
    
    # Mock logic (Replace with your DB query)
    img_size = 40  # 40%
    vid_size = 30  # 30%
    doc_size = 15  # 15%
    
    return dict(img_pct=img_size, vid_pct=vid_size, doc_pct=doc_size)

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        # Form-la irunthu details-ah edukkirom
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')

        # Basic Password Validation
        if password != confirm_password:
            return "Passwords do not match!", 400

        try:
            # 1. Supabase Auth-la user create panrom
            auth_res = supabase.auth.sign_up({"email": email, "password": password})
            
            if auth_res.user:
                # 2. Auth success aana, 'users' table-la name details-ah insert panrom
                # Inga Table-la 'first_name', 'last_name' columns irukanum
                supabase.table('users').insert({
                    "id": auth_res.user.id, # Auth ID match panna
                    "first_name": first_name,
                    "last_name": last_name,
                    "email": email,
                    "username": f"{first_name} {last_name}" # Combined name for profile
                }).execute()

                return "Signup Success! Check your email to verify, then Login."
            
        except Exception as e:
            print(f"Signup Error: {e}")
            return f"Signup failed: {str(e)}"

    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        try:
            res = supabase.auth.sign_in_with_password({"email": email, "password": password})
            session['user_id'] = res.user.id
            session['user_email'] = res.user.email
            log_activity(res.user.id, "Login", "User logged into the system")
            return redirect(url_for('index'))
        except Exception as e:
            return f"Login failed: {str(e)}"
    return render_template('login.html')

@app.route('/logout')
def logout():
    if 'user_id' in session:
        log_activity(session['user_id'], "Logout", "User logged out")
    session.clear()
    return redirect(url_for('login'))

# --- FILE OPERATIONS ---
@app.route('/upload', methods=['POST'])
def upload():
    if 'user_id' not in session: return redirect(url_for('login'))
    
    user_id = session['user_id']
    file = request.files['file']
    folder_id = request.form.get('folder_id')
    
    if file:
        safe_name = secure_filename(file.filename)
        file_content = file.read()
        
        # 1. Quota Check (Existing)
        usage = get_storage_usage(user_id)
        if usage + (len(file_content)/(1024*1024)) > 100:
            return "Quota Exceeded", 403

        # 2. Check if file already exists (Versioning Logic)
        existing_file = supabase.table("file_metadata").select("*").eq("user_id", user_id).eq("file_name", safe_name).eq("is_deleted", False).execute()

        if existing_file.data:
            # IT'S A NEW VERSION
            file_id = existing_file.data[0]['id']
            # Get latest version number
            versions = supabase.table("file_versions").select("version_number").eq("file_id", file_id).order("version_number", desc=True).limit(1).execute()
            next_version = (versions.data[0]['version_number'] + 1) if versions.data else 2
            
            # Save with version suffix in storage
            file_path = f"{user_id}/v{next_version}_{safe_name}"
        else:
            # IT'S A NEW FILE
            file_id = None
            next_version = 1
            file_path = f"{user_id}/{safe_name}"

        # 3. Upload to Storage
        supabase.storage.from_("files").upload(path=file_path, file=file_content, file_options={"upsert": "true"})
        file_url = supabase.storage.from_("files").get_public_url(file_path)

        if not file_id:
            # Insert new metadata
            res = supabase.table("file_metadata").insert({
                "file_name": safe_name, "file_url": file_url, "file_size": len(file_content),
                "user_id": user_id, "folder_id": int(folder_id) if folder_id else None
            }).execute()
            file_id = res.data[0]['id']
        else:
            # Update existing metadata to point to latest
            supabase.table("file_metadata").update({
                "file_url": file_url, "file_size": len(file_content)
            }).eq("id", file_id).execute()

        # 4. Record the Version
        supabase.table("file_versions").insert({
            "file_id": file_id, "version_number": next_version,
            "storage_key": file_path, "file_url": file_url, "size_bytes": len(file_content)
        }).execute()

        log_activity(user_id, "Uploaded File", f"{safe_name} (v{next_version})")

    return redirect(request.referrer or url_for('index'))

@app.route('/create_folder', methods=['POST'])
def create_folder():
    if 'user_id' not in session: return redirect(url_for('login'))
    
    name = request.form.get('folder_name')
    parent_id = request.form.get('parent_id')
    
    data = {
        "name": name,
        "user_id": session['user_id'],
        "parent_id": int(parent_id) if parent_id else None
    }
    supabase.table("folders").insert(data).execute()
    log_activity(session['user_id'], "Created Folder", f"Folder: {name}")
    
    if parent_id:
        return redirect(url_for('index', folder_id=parent_id))
    return redirect(url_for('index'))

# --- TRASH & STARRED ---

@app.route('/move_to_trash/<int:file_id>')
def move_to_trash(file_id):
    supabase.table("file_metadata").update({"is_deleted": True}).eq("id", file_id).execute()
    log_activity(session['user_id'], "Moved to Trash", f"File ID: {file_id}")
    return redirect(request.referrer)

@app.route('/restore/<int:file_id>')
def restore_file(file_id):
    supabase.table("file_metadata").update({"is_deleted": False}).eq("id", file_id).execute()
    log_activity(session['user_id'], "Restored File", f"File ID: {file_id}")
    return redirect(url_for('trash_view'))

@app.route('/permanent_delete/<int:file_id>/<path:filename>')
def permanent_delete(file_id, filename):
    user_id = session['user_id']
    file_path = f"{user_id}/{filename}"
    try:
        supabase.storage.from_("files").remove([file_path])
        supabase.table("file_metadata").delete().eq("id", file_id).execute()
        log_activity(user_id, "Permanently Deleted", f"File: {filename}")
    except Exception as e:
        print(f"Error: {e}")
    return redirect(url_for('trash_view'))

@app.route('/trash')
def trash_view():
    user_id = session.get('user_id')
    # Function call panni variable-la store pannunga
    current_usage = get_storage_usage(user_id) 
    
    # Files fetch panra logic...
    files = supabase.table("file_metadata").select("*").eq("user_id", user_id).eq("is_deleted", True).execute().data
    user_email = session.get('user_email')
    profile_pic = None
    
    if user_email:
        # Database-la irunthu profile pic URL-ah edukkirom
        user_res = supabase.table('users').select("profile_pic_url").eq("email", user_email).execute()
        if user_res.data:
            profile_pic = user_res.data[0].get('profile_pic_url')
    # Inga 'usage=current_usage' nu kudukkanum
    return render_template('trash.html', files=files, usage=current_usage, quota=100, profile_pic=profile_pic)

@app.route('/toggle_star/<int:file_id>')
def toggle_star(file_id):
    res = supabase.table("file_metadata").select("is_starred").eq("id", file_id).single().execute()
    supabase.table("file_metadata").update({"is_starred": not res.data['is_starred']}).eq("id", file_id).execute()
    return redirect(request.referrer)
@app.route('/starred')
def starred_view():
    # 1. Session check (Idhu iruntha thaan error varaathu)
    user_id = session.get('user_id')
    if not user_id:
        return redirect('/login')

    # 2. DEBUG: Terminal-la check panna intha print-ah paarunga
    print(f"DEBUG: Starred page loaded for user: {user_id}")

    # 3. Storage calculate panra function-ah call pannunga
    usage = get_storage_usage(user_id)
    print(f"DEBUG: Storage usage: {usage} MB")

    # 4. Starred files fetch pannunga
    files = supabase.table("file_metadata") \
        .select("*") \
        .eq("user_id", user_id) \
        .eq("is_starred", True) \
        .eq("is_deleted", False) \
        .execute()
    user_email = session.get('user_email')
    profile_pic = None
    
    if user_email:
        # Database-la irunthu profile pic URL-ah edukkirom
        user_res = supabase.table('users').select("profile_pic_url").eq("email", user_email).execute()
        if user_res.data:
            profile_pic = user_res.data[0].get('profile_pic_url')
    # 5. Ellaa variable-ayum template-kku anuppunga
    return render_template('starred.html', 
                           files=files.data, 
                           usage=usage, 
                           quota=100,
                           profile_pic=profile_pic)

                         
@app.route('/activity')
def activity_view():
    if 'user_id' not in session: return redirect(url_for('login'))
    user_id = session['user_id']
    logs = supabase.table("activity_logs").select("*").eq("user_id", user_id).order("created_at", desc=True).limit(20).execute()
    usage = get_storage_usage(user_id)
    user_email = session.get('user_email')
    profile_pic = None
    
    if user_email:
        # Database-la irunthu profile pic URL-ah edukkirom
        user_res = supabase.table('users').select("profile_pic_url").eq("email", user_email).execute()
        if user_res.data:
            profile_pic = user_res.data[0].get('profile_pic_url')
    return render_template('activity.html', logs=logs.data, usage=usage, quota=100, profile_pic=profile_pic)



# --- MODIFIED SHARE ROUTE ---
@app.route('/share_file', methods=['POST'])
def share_file():
    file_id = request.form.get('file_id')
    target_email = request.form.get('share_with_email')
    expires_at_str = request.form.get('expires_at') 

    try:
        # DB-la insert panra logic
        share_data = {
            "file_id": file_id,
            "shared_with_email": target_email,
            "permission_type": "viewer",
            "expires_at": expires_at_str 
        }
        supabase.table("file_shares").insert(share_data).execute()
        
        # --- AUTOMATIC MAIL LOGIC ---
        if expires_at_str:
            # Expiry time-ah datetime object-ah mathurathu
            expiry_time = datetime.fromisoformat(expires_at_str)
            now = datetime.now()
            
            # Total duration calculate panni, athula 75% time kandupudikanum
            total_diff = (expiry_time - now).total_seconds()
            alert_seconds = total_diff * 0.75
            alert_time = now + timedelta(seconds=alert_seconds)

            # Get filename for the mail
            file_info = supabase.table("file_metadata").select("file_name").eq("id", file_id).single().execute()
            filename = file_info.data['file_name']

            # Scheduler-la task add panrathu
            scheduler.add_job(
                func=send_expiry_alert,
                trigger='date',
                run_date=alert_time,
                args=[target_email, filename]
            )

        log_activity(session['user_id'], "Shared File", f"Shared with: {target_email}")
        return redirect(url_for('index'))
    except Exception as e:
        print(f"Error: {e}")
        return "Sharing failed", 500

@app.route('/shared')
def shared_with_me():
    user_id = session.get('user_id')
    user_email = session.get('user_email')

    if not user_id or not user_email:
        return redirect('/login')

    # 1. Calculate Storage (Ithu thaan sidebar-ku venum)
    usage = get_storage_usage(user_id)

    # 2. Cleanup: Expired shares-ah delete pannunga
    current_time = datetime.now().isoformat()
    supabase.table("file_shares") \
        .delete() \
        .eq("shared_with_email", user_email) \
        .lt("expires_at", current_time) \
        .execute()

    # 3 & 4. Fetch file metadata PLUS owner info using Joins
    # Inga file_shares table-la irunthu file_metadata-vum, athula irunthu profiles (owner) edukurom
    # 3. Get shared files
    # 3. Get shared files and their metadata
    shared_res = supabase.table("file_shares") \
        .select("*, file_metadata(*)") \
        .eq("shared_with_email", user_email) \
        .execute()

    files = []
    for item in shared_res.data:
        file_info = item.get('file_metadata')
        if file_info:
            # Carry over sharing-specific info to the file object
            file_info['expires_at'] = item.get('expires_at')
            
            # Use 'sender_email' if it exists in your file_shares table
            # Otherwise, we'll handle the naming in the template
            file_info['owner_email'] = item.get('sender_email') 
            
            # Ensure we have the ID for the dropdown menu
            file_info['id'] = file_info.get('id')
            
            files.append(file_info)
    user_email = session.get('user_email')
    profile_pic = None
    
    if user_email:
        # Database-la irunthu profile pic URL-ah edukkirom
        user_res = supabase.table('users').select("profile_pic_url").eq("email", user_email).execute()
        if user_res.data:
            profile_pic = user_res.data[0].get('profile_pic_url')
    return render_template('shared.html', 
                           files=files, 
                           usage=usage, 
                           quota=100, profile_pic=profile_pic)
@app.route('/folder/<folder_id>')
def view_folder(folder_id):
    user_id = session.get('user_id')
    
    # 1. Fetch current folder name (Breadcrumbs-kaga)
    current_folder = supabase.table("folders").select("name").eq("id", folder_id).single().execute()
    
    # 2. Fetch SUB-FOLDERS inside this folder
    sub_folders = supabase.table("folders") \
        .select("*") \
        .eq("user_id", user_id) \
        .eq("parent_id", folder_id) \
        .execute()
        
    # 3. Fetch FILES inside this folder
    folder_files = supabase.table("file_metadata") \
        .select("*") \
        .eq("user_id", user_id) \
        .eq("folder_id", folder_id) \
        .execute()

    return render_template('shared.html', 
                           folders=sub_folders.data, 
                           files=folder_files.data, 
                           current_folder_id=folder_id,
                           current_folder_name=current_folder.data['name'])


@app.route('/search')
def search():
    if 'user_id' not in session: return redirect(url_for('login'))
    query = request.args.get('query', '')
    file_type = request.args.get('type')
    sort_by = request.args.get('sort', 'created_at')

    db_query = supabase.table("file_metadata").select("*").eq("user_id", session['user_id']).ilike("file_name", f"%{query}%").eq("is_deleted", False)
    if file_type:
        db_query = db_query.ilike("file_name", f"%.{file_type}")

    res = db_query.order(sort_by, desc=True).execute()
    usage = get_storage_usage(session['user_id'])
    return render_template('index.html', files=res.data, folders=[], usage=usage, quota=100)

@app.route('/file_history/<int:file_id>')
def file_history(file_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    
    versions = supabase.table("file_versions").select("*").eq("file_id", file_id).order("version_number", desc=True).execute()
    file_info = supabase.table("file_metadata").select("file_name").eq("id", file_id).single().execute()
    
    return render_template('history.html', versions=versions.data, filename=file_info.data['file_name'])

@app.route('/rename_folder/<int:folder_id>')
def rename_folder(folder_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    
    new_name = request.args.get('new_name')
    if new_name:
        supabase.table("folders").update({"name": new_name}).eq("id", folder_id).execute()
        log_activity(session['user_id'], "Renamed Folder", f"New Name: {new_name}")
    
    return redirect(request.referrer or url_for('index'))
@app.route('/rename_file/<int:file_id>')
def rename_file(file_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    
    new_name = request.args.get('new_name')
    if new_name:
        supabase.table("file_metadata").update({"file_name": new_name}).eq("id", file_id).execute()
        log_activity(session['user_id'], "Renamed File", f"New Name: {new_name}")
        
    return redirect(request.referrer or url_for('index'))

@app.route('/delete_folder/<int:folder_id>')
def delete_folder(folder_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    
    # Folder-ah delete panna athula irukira files-um logic-padi handle pannanum
    # Ippo simple-ah folder-ah mattum delete panna:
    supabase.table("folders").delete().eq("id", folder_id).execute()
    log_activity(session['user_id'], "Deleted Folder", f"Folder ID: {folder_id}")
    
    return redirect(request.referrer or url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)