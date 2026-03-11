import time
import requests
from datetime import date, timedelta


class TogglClient:
    def __init__(self, token: str, workspace_id: int):
        self.workspace_id = workspace_id
        self.auth = (token, "api_token")
        self.base = "https://api.track.toggl.com/api/v9"

    def _get(self, path: str, **params):
        r = requests.get(
            f"{self.base}{path}",
            auth=self.auth,
            params=params or None,
            timeout=10,
        )
        r.raise_for_status()
        return r.json()

    def projects(self) -> dict:
        """Returns {project_id: {name, color}}"""
        raw = self._get(f"/workspaces/{self.workspace_id}/projects", active=True)
        return {
            p["id"]: {"name": p["name"], "color": p.get("color", "#888888")}
            for p in raw
        }

    def time_entries(self, start: date, end: date) -> list:
        """Returns all entries in [start, end]. Running timers get elapsed time."""
        now_ts = time.time()
        raw = self._get(
            "/me/time_entries",
            start_date=start.isoformat(),
            end_date=(end + timedelta(days=1)).isoformat(),
        )
        result = []
        self.timer_running = False
        for e in raw:
            dur = e.get("duration", 0)
            if dur > 0:
                e["_hours"] = dur / 3600
                result.append(e)
            elif dur < 0:
                # Running timer: Toggl sets duration = -(unix start timestamp)
                e["_hours"] = (now_ts + dur) / 3600
                e["_running"] = True
                self.timer_running = True
                result.append(e)
        return result
