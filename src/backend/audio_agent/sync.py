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


def ensure_fresh(category: str, min_downloaded: int = 5,
                 max_downloads: int = 40) -> bool:
    """Make sure the local library has enough ``category`` sounds.

    If fewer than ``min_downloaded`` sounds are stored locally, a background
    sync is kicked off (non-blocking) so the library keeps filling itself
    with trending sounds. Returns True when the library already has enough,
    False when a sync was triggered (caller should use what's available —
    the next run will have more). Never raises.
    """
    try:
        lib = AudioLibrary()
        data = lib.browse(category=category, downloaded_only=True,
                          per_page=1)
        count = int(data.get("total", 0) or 0)
        if count < min_downloaded:
            print(f"[AudioAgent Sync] Library thin on '{category}' "
                  f"({count} < {min_downloaded}) — triggering background sync.")
            lib.log("ensure_fresh_triggered", f"category={category} count={count}")
            start_background_sync(max_downloads=max_downloads)
            return False
        return True
    except Exception as e:
        print(f"[AudioAgent Sync] ensure_fresh note: {e}")
        return True
