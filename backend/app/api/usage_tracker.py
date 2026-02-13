import json
import os
import threading
from datetime import datetime

class UsageTracker:
    def __init__(self, file_path="usage.json"):
        self.file_path = file_path
        self.lock = threading.Lock()
        self._ensure_file_exists()

    def _ensure_file_exists(self):
        if not os.path.exists(self.file_path):
            with open(self.file_path, "w") as f:
                json.dump({
                    "total_usd": 0.0,
                    "estimated_savings_usd": 0.0,
                    "messages_count": 0,
                    "last_updated": datetime.now().isoformat()
                }, f)

    def log_usage(self, cost_usd, is_local_voice=False):
        # Local voice savings calculation (OpenAI TTS-1-HD cost is ~$0.03 per 1000 chars)
        # We assume an average of 500 characters per message for estimation
        savings = 0.015 if is_local_voice else 0.0
        
        with self.lock:
            try:
                with open(self.file_path, "r") as f:
                    data = json.load(f)
                
                data["total_usd"] += cost_usd
                data["estimated_savings_usd"] += savings
                data["messages_count"] += 1
                data["last_updated"] = datetime.now().isoformat()
                
                with open(self.file_path, "w") as f:
                    json.dump(data, f, indent=2)
            except Exception as e:
                print(f"Error logging usage: {e}")

    def get_stats(self):
        with self.lock:
            try:
                with open(self.file_path, "r") as f:
                    return json.load(f)
            except:
                return {}

usage_tracker = UsageTracker()
