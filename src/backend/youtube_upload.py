import os
import threading
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.auth.exceptions import RefreshError
from src.backend.youtube_auth import get_user_credentials
import json
from src.database import store_youtube_credentials

# Thread-safe upload status registry
# Key: user_id (int), Value: dict {"progress": int, "status": str, "video_id": str/None, "error": str/None}
_upload_status = {}
_upload_status_lock = threading.Lock()

def get_upload_status(user_id: int) -> dict:
    """Thread-safe getter for a user's upload status."""
    with _upload_status_lock:
        return _upload_status.get(user_id, {"progress": 0, "status": "idle"})

def set_upload_status(user_id: int, status_dict: dict):
    """Thread-safe setter for a user's upload status."""
    with _upload_status_lock:
        _upload_status[user_id] = status_dict

def upload_video(user_id, file_path, title, description, category_id="22", tags=None):
    if tags is None:
        tags = []
        
    set_upload_status(user_id, {"progress": 0, "status": "starting", "video_id": None, "error": None})
    
    credentials = get_user_credentials(user_id)
    if not credentials:
        err_msg = "No YouTube credentials found for user."
        set_upload_status(user_id, {"progress": 0, "status": "failed", "video_id": None, "error": err_msg})
        raise ValueError(err_msg)
        
    try:
        youtube = build('youtube', 'v3', credentials=credentials)
        
        body = {
            'snippet': {
                'title': title,
                'description': description,
                'tags': tags,
                'categoryId': category_id
            },
            'status': {
                'privacyStatus': 'private' # Default to private
            }
        }
        
        # Enforce smaller chunksize for smooth real-time progress updates (e.g. 1MB chunksize)
        media = MediaFileUpload(file_path, chunksize=1024*1024, resumable=True)
        
        request = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media
        )
        
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                progress_pct = int(status.progress() * 100)
                set_upload_status(user_id, {"progress": progress_pct, "status": "uploading", "video_id": None, "error": None})
                print(f"Uploaded {progress_pct}%")
                
        video_id = response.get('id')
        set_upload_status(user_id, {"progress": 100, "status": "completed", "video_id": video_id, "error": None})
        print(f"Upload Complete! Video ID: {video_id}")
        return video_id
        
    except RefreshError as e:
        err_msg = f"Token refresh failed: {e}"
        set_upload_status(user_id, {"progress": 0, "status": "failed", "video_id": None, "error": err_msg})
        print(err_msg)
        raise e
    except Exception as e:
        err_msg = f"An error occurred during YouTube upload: {e}"
        set_upload_status(user_id, {"progress": 0, "status": "failed", "video_id": None, "error": err_msg})
        print(err_msg)
        raise e

