"""
audio_agent/sync.py
Background periodic sync runner for Audio Intelligence Agent.
Runs the scrapers to fetch trending viral sounds and indexes them in the SQLite library.
"""
import os
import sys
import threading
import time
from .library import AudioLibrary
from .scraper import AudioScraper

_sync_lock = threading.Lock()
_active_sync_thread = None

def run_sync_job(max_downloads: int = 50) -> dict:
    """Synchronously execute the full library sync and download process."""
    global _sync_lock
    if not _sync_lock.acquire(blocking=False):
        print("[AudioAgent Sync] Sync already in progress, skipping request.")
        return {"status": "error", "message": "Sync already in progress"}
        
    try:
        lib = AudioLibrary()
        scraper = AudioScraper(library=lib)
        
        lib.log("sync_job_started", "Initiating scheduled library sync")
        results = scraper.run_full_sync(max_downloads=max_downloads)
        lib.log("sync_job_finished", "Finishedscheduled library sync")
        
        return {
            "status": "success",
            "results": results
        }
    except Exception as e:
        print(f"[AudioAgent Sync] Sync failed: {e}")
        try:
            AudioLibrary().log("sync_job_failed", str(e))
        except Exception:
            pass
        return {"status": "error", "error": str(e)}
    finally:
        _sync_lock.release()

def start_background_sync(max_downloads: int = 50) -> bool:
    """Spawns a thread to run the sync in the background if not already running."""
    global _active_sync_thread
    
    if _sync_lock.locked():
        return False
        
    _active_sync_thread = threading.Thread(
        target=run_sync_job,
        args=(max_downloads,),
        name="AudioAgentSyncThread",
        daemon=True
    )
    _active_sync_thread.start()
    return True

if __name__ == "__main__":
    print("=== Audio Agent Sync CLI CLI ===")
    start_time = time.time()
    res = run_sync_job(max_downloads=40)
    print(f"Sync took {time.time() - start_time:.2f} seconds.")
    print("Results:", res)
    sys.exit(0)
