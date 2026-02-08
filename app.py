import os
from flask import Flask, render_template, request, redirect, url_for, session
from supabase import create_client, Client
from dotenv import load_dotenv
import urllib.parse
from werkzeug.utils import secure_filename
from flask_cors import CORS 
from datetime import datetime

load_dotenv()

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
    """Calculates total storage used by the user in MB"""
    try:
        res = supabase.table("file_metadata").select("file_size").eq("user_id", user_id).eq("is_deleted", False).execute()
        total_bytes = sum(item['file_size'] for item in res.data)
        total_mb = round(total_bytes / (1024 * 1024), 2)
        return total_mb
    except Exception:
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

    return render_template(
        'index.html', 
        folders=folders_list, 
        files=files_list, 
        current_folder_id=folder_id,
        current_folder_name=current_folder_name,
        breadcrumbs=breadcrumbs,
        usage=usage,
        quota=quota
    )

   

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        try:
            supabase.auth.sign_up({"email": email, "password": password})
            return "Signup Success! Check your email and then Login."
        except Exception as e:
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
    files = supabase.table("file_metadata").select("*").eq("user_id", session['user_id']).eq("is_deleted", True).execute()
    return render_template('trash.html', files=files.data)

@app.route('/toggle_star/<int:file_id>')
def toggle_star(file_id):
    res = supabase.table("file_metadata").select("is_starred").eq("id", file_id).single().execute()
    supabase.table("file_metadata").update({"is_starred": not res.data['is_starred']}).eq("id", file_id).execute()
    return redirect(request.referrer)

@app.route('/starred')
def starred_view():
    files = supabase.table("file_metadata").select("*").eq("user_id", session['user_id']).eq("is_starred", True).eq("is_deleted", False).execute()
    return render_template('starred.html', files=files.data)

@app.route('/profile', methods=['GET', 'POST'])
def profile_page():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    message = None
    if request.method == 'POST':
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        
        if new_password == confirm_password:
            try:
                # Supabase Auth logic to update password
                supabase.auth.update_user({"password": new_password})
                message = "Password updated successfully!"
                log_activity(session['user_id'], "Security", "User changed their password")
            except Exception as e:
                message = f"Error: {str(e)}"
        else:
            message = "Passwords do not match!"

    usage = get_storage_usage(session['user_id'])
    return render_template('profile.html', 
                           user_email=session.get('user_email'), 
                           usage=usage, 
                           quota=100, 
                           message=message)

# --- SHARING, SEARCH & ACTIVITY ---

@app.route('/activity')
def activity_view():
    if 'user_id' not in session: return redirect(url_for('login'))
    user_id = session['user_id']
    logs = supabase.table("activity_logs").select("*").eq("user_id", user_id).order("created_at", desc=True).limit(20).execute()
    usage = get_storage_usage(user_id)
    return render_template('activity.html', logs=logs.data, usage=usage, quota=100)

@app.route('/share_file', methods=['POST'])
def share_file():
    file_id = request.form.get('file_id')
    target_email = request.form.get('share_with_email')
    expires_at = request.form.get('expires_at') 

    try:
        share_data = {
            "file_id": file_id,
            "shared_with_email": target_email,
            "permission_type": "viewer",
            "expires_at": expires_at 
        }
        supabase.table("file_shares").insert(share_data).execute()
        log_activity(session['user_id'], "Shared File", f"Shared with: {target_email}")
        return redirect(url_for('index'))
    except Exception as e:
        print(f"Error: {e}")
        return "Sharing failed", 500

@app.route('/shared')
def shared_with_me():
    user_email = session.get('user_email')
    current_time = datetime.now().isoformat()
    supabase.table("file_shares").delete().eq("shared_with_email", user_email).lt("expires_at", current_time).execute()
    shared_res = supabase.table("file_shares").select("file_id").eq("shared_with_email", user_email).execute()
    
    file_ids = [item['file_id'] for item in shared_res.data]
    if not file_ids: 
        return render_template('shared.html', files=[])

    files_res = supabase.table("file_metadata").select("*").in_("id", file_ids).execute()
    return render_template('shared.html', files=files_res.data)

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

if __name__ == '__main__':
    app.run(debug=True)