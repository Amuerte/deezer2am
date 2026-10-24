"""Small HTTP client for the public Deezer API (https://api.deezer.com).

Only public data is reachable without OAuth: a user's public playlists,
playlist tracks and track details (including the ISRC code).
"""

import os
from time import sleep

import requests
from loguru import logger


class DeezerError(Exception):
    """Error returned by the Deezer API (sent with HTTP 200 and an "error" key)."""

    def __init__(self, error):
        self.type = error.get("type")
        self.code = error.get("code")
        super().__init__(f"{self.type} ({self.code}): {error.get('message')}")


class DeezerApi:
    BASE_URL = "https://api.deezer.com"
    # Deezer allows 50 requests per 5 seconds and answers with this code past it
    QUOTA_ERROR_CODE = 4

    def __init__(self, user_id=None, timeout=10, max_retries=3):
        self.user_id = user_id or os.environ.get("DEEZER_USER_ID")
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = requests.Session()

    def _request(self, url, params=None):
        for attempt in range(self.max_retries + 1):
            logger.debug("GET {} {}", url, params or "")
            response = self.session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            body = response.json()
            error = body.get("error") if isinstance(body, dict) else None
            if not error:
                return body
            if error.get("code") == self.QUOTA_ERROR_CODE and attempt < self.max_retries:
                logger.warning("Deezer quota exceeded, retrying in 5s ({}/{})",
                               attempt + 1, self.max_retries)
                sleep(5)
                continue
            raise DeezerError(error)

    def _get(self, path, params=None):
        return self._request(f"{self.BASE_URL}/{path.lstrip('/')}", params)

    def _get_all(self, path, limit=100):
        """Fetch every page of a paginated endpoint by following the "next" links.

        Returns the first page's response with the "data" of the following pages
        appended to it, so it reads as a single, complete API response.
        """
        response = self._get(path, {"limit": limit})
        page = response
        while page.get("next"):
            page = self._request(page["next"])
            response.setdefault("data", []).extend(page.get("data", []))
        response.pop("next", None)
        return response

    def get_user_playlists(self, user_id=None, raw=False):
        """Return the public playlists of a user (DEEZER_USER_ID by default).

        With raw=True, return the whole API response instead of its "data" list.
        """
        user_id = user_id or self.user_id
        if not user_id:
            raise ValueError("No user id given and DEEZER_USER_ID is not set")
        response = self._get_all(f"user/{user_id}/playlists")
        return response if raw else response.get("data", [])

    def get_playlist_tracks(self, playlist_id, raw=False):
        """Return all the tracks of a playlist.

        With raw=True, return the whole API response instead of its "data" list.
        """
        response = self._get_all(f"playlist/{playlist_id}/tracks")
        return response if raw else response.get("data", [])

    def get_track(self, track_id):
        """Return the details of a track, including its ISRC code."""
        return self._get(f"track/{track_id}")
