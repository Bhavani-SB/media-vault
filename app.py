import os
from flask import Flask, render_template, request, redirect, url_for, session
from supabase import create_client, Client
from dotenv import load_dotenv
import urllib.parse
from werkzeug.utils import secure_filename
from flask_cors import CORS 
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

# --- ROUTES ---

@app.route('/')
@app.route('/folder/<int:folder_id>')
def index(folder_id=None):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    
    # 1. Fetch Folders
    folder_query = supabase.table("folders").select("*").eq("user_id", user_id)
    if folder_id:
        folder_query = folder_query.eq("parent_id", folder_id)
    else:
        folder_query = folder_query.is_("parent_id", "null")
    folders_list = folder_query.execute().data

    # 2. Fetch Files (Not in trash)
    file_query = supabase.table("file_metadata").select("*").eq("user_id", user_id).eq("is_deleted", False)
    if folder_id:
        file_query = file_query.eq("folder_id", folder_id)
    else:
        file_query = file_query.is_("folder_id", "null")
    files_list = file_query.execute().data

    # Current folder name fetch (for breadcrumbs)
    current_folder_name = ""
    if folder_id:
        folder_data = supabase.table("folders").select("name").eq("id", folder_id).single().execute()
        current_folder_name = folder_data.data['name']

    return render_template('index.html', 
                           folders=folders_list, 
                           files=files_list, 
                           current_folder_id=folder_id,
                           current_folder_name=current_folder_name)

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
            return redirect(url_for('index'))
        except Exception as e:
            return f"Login failed: {str(e)}"
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# --- FILE OPERATIONS ---

@app.route('/upload', methods=['POST'])
def upload():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    file = request.files['file']
    folder_id = request.form.get('folder_id')
    
    if file:
        safe_name = secure_filename(file.filename)
        file_content = file.read()
        file_path = f"{session['user_id']}/{safe_name}"

        # Upload to Storage
        supabase.storage.from_("files").upload(
            path=file_path,
            file=file_content,
            file_options={"content-type": file.content_type, "upsert": "true"}
        )

        file_url = supabase.storage.from_("files").get_public_url(file_path)

        # DB Entry
        data = {
            "file_name": safe_name,
            "file_url": file_url,
            "file_size": len(file_content),
            "user_id": session['user_id'],
            "folder_id": int(folder_id) if folder_id else None
        }
        supabase.table("file_metadata").insert(data).execute()
        
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
    
    if parent_id:
        return redirect(url_for('index', folder_id=parent_id))
    return redirect(url_for('index'))

# --- TRASH & STARRED ---

@app.route('/move_to_trash/<int:file_id>')
def move_to_trash(file_id):
    supabase.table("file_metadata").update({"is_deleted": True}).eq("id", file_id).execute()
    return redirect(request.referrer)

@app.route('/restore/<int:file_id>')
def restore_file(file_id):
    supabase.table("file_metadata").update({"is_deleted": False}).eq("id", file_id).execute()
    return redirect(url_for('trash_view'))

@app.route('/permanent_delete/<int:file_id>/<path:filename>')
def permanent_delete(file_id, filename):
    user_id = session['user_id']
    file_path = f"{user_id}/{filename}"
    try:
        supabase.storage.from_("files").remove([file_path])
        supabase.table("file_metadata").delete().eq("id", file_id).execute()
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

@app.route('/profile')
def profile_page():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('profile.html', user_email=session.get('user_email'))
# --- SHARING & SEARCH ---

@app.route('/share_file', methods=['POST'])
def share_file():
    file_id = request.form.get('file_id')
    target_email = request.form.get('share_with_email') # Intha name HTML-oda match aaganum

    if not file_id or not target_email:
        print("Error: Missing file_id or email")
        return redirect(url_for('index'))

    try:
        # Permission_type column database-la iruntha ithai add pannunga
        share_data = {
            "file_id": file_id,
            "shared_with_email": target_email,
            "permission_type": "viewer" 
        }
        
        supabase.table("file_shares").insert(share_data).execute()
        return redirect(url_for('index'))
        
    except Exception as e:
        print(f"Database Error: {e}")
        return "Sharing failed", 500

@app.route('/shared')
def shared_with_me():
    user_email = session.get('user_email')
    shared_res = supabase.table("file_shares").select("file_id, permission_type").eq("shared_with_email", user_email).execute()
    
    share_map = {item['file_id']: item['permission_type'] for item in shared_res.data}
    file_ids = list(share_map.keys())
    
    if not file_ids: return render_template('shared.html', files=[])

    files_res = supabase.table("file_metadata").select("*").in_("id", file_ids).execute()
    final_files = []
    for f in files_res.data:
        f['permission'] = share_map.get(f['id'])
        final_files.append(f)
    return render_template('shared.html', files=final_files)

@app.route('/search')
def search():
    query = request.args.get('query')
    res = supabase.table("file_metadata").select("*").eq("user_id", session['user_id']).ilike("file_name", f"%{query}%").eq("is_deleted", False).execute()
    return render_template('index.html', files=res.data, folders=[])

if __name__ == '__main__':
    app.run(debug=True)