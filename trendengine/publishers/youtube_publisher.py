"""YouTube Shorts publisher — the first REAL auto-publisher.

Uploads a rendered vertical video via the official YouTube Data API v3
(`videos.insert`, resumable) and reads back public stats for the learning loop
(`videos.list?part=statistics`). Uploading needs OAuth (an API key is read-only),
so run `python run.py youtube-auth` once to cache a refresh token.

Quota note: the free tier is ~10,000 units/day and an upload costs ~1,600, so
you can realistically upload ~5-6/day. The autopilot canary caps stay under this.

This is an official, ToS-compliant route — no scraping. Even so, autopilot only
uploads when you set autopilot.mode: live; in shadow mode nothing is sent.
"""
from __future__ import annotations

from pathlib import Path

from trendengine.config import Config
from trendengine.db.models import Draft
from trendengine.logging_setup import get_logger
from trendengine.publishers.base import Publisher, PublishResult

log = get_logger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]


def _default_token_path() -> Path:
    return Path.home() / ".config" / "trend-engine" / "youtube_token.json"


class YouTubePublisher(Publisher):
    name = "youtube"

    def __init__(self, config: Config) -> None:
        super().__init__(config)
        self.yt = config.raw.get("youtube", {})
        tok = self.yt.get("token_file") or ""
        self.token_path = Path(tok) if tok else _default_token_path()
        self._service = None

    # -- auth --------------------------------------------------------------
    def authorize(self) -> None:
        """Run the one-time OAuth browser flow and cache the token."""
        from google_auth_oauthlib.flow import InstalledAppFlow

        client_secret = Config.env("YOUTUBE_OAUTH_CLIENT_SECRET", "./client_secret.json")
        if not client_secret or not Path(client_secret).exists():
            raise FileNotFoundError(
                f"OAuth client secret not found at '{client_secret}'. Create a "
                "'Desktop app' OAuth client in Google Cloud Console, download the "
                "JSON, and set YOUTUBE_OAUTH_CLIENT_SECRET in .env.")
        flow = InstalledAppFlow.from_client_secrets_file(client_secret, SCOPES)
        creds = flow.run_local_server(port=0)
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_path.write_text(creds.to_json(), encoding="utf-8")
        self.token_path.chmod(0o600)
        log.info("YouTube token saved to %s", self.token_path)

    def _credentials(self):
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        if not self.token_path.exists():
            raise RuntimeError(
                "No YouTube token. Run `python run.py youtube-auth` first.")
        creds = Credentials.from_authorized_user_file(str(self.token_path), SCOPES)
        if not creds.valid and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            self.token_path.write_text(creds.to_json(), encoding="utf-8")
        return creds

    def service(self):
        if self._service is None:
            from googleapiclient.discovery import build
            self._service = build("youtube", "v3", credentials=self._credentials(),
                                  cache_discovery=False)
        return self._service

    def health_check(self) -> tuple[bool, str]:
        if not self.token_path.exists():
            return False, "no YouTube token (run: python run.py youtube-auth)"
        try:
            self._credentials()
            return True, "youtube auth ready"
        except Exception as exc:  # noqa: BLE001
            return False, f"youtube auth error: {exc}"

    # -- prepare (assisted fallback) ---------------------------------------
    def prepare(self, draft: Draft) -> PublishResult:
        from trendengine.publishers.assisted import AssistedPublisher
        return AssistedPublisher(self.config).prepare(draft)

    # -- publish (real upload) ---------------------------------------------
    def publish(self, draft: Draft) -> PublishResult:
        from googleapiclient.http import MediaFileUpload

        if not draft.video_path or not Path(draft.video_path).exists():
            return PublishResult(ok=False,
                                 message="No rendered video to upload.")
        title, description, tags = self._metadata(draft)
        body = {
            "snippet": {
                "title": title[:100],
                "description": description[:5000],
                "tags": tags[:15],
                "categoryId": str(self.yt.get("category_id", "28")),
            },
            "status": {
                "privacyStatus": self.yt.get("privacy_status", "public"),
                "selfDeclaredMadeForKids": bool(self.yt.get("made_for_kids", False)),
            },
        }
        media = MediaFileUpload(draft.video_path, chunksize=-1, resumable=True,
                                mimetype="video/*")
        request = self.service().videos().insert(
            part="snippet,status", body=body, media_body=media)

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                log.info("Upload %d%%", int(status.progress() * 100))
        video_id = response.get("id")
        log.info("Uploaded draft #%d -> https://youtube.com/watch?v=%s",
                 draft.id, video_id)
        return PublishResult(ok=True, message=f"Uploaded: {video_id}",
                             external_post_id=video_id)

    # -- stats for the learning loop ---------------------------------------
    def fetch_stats(self, video_id: str) -> dict | None:
        resp = self.service().videos().list(
            part="statistics", id=video_id).execute()
        items = resp.get("items", [])
        if not items:
            return None
        st = items[0].get("statistics", {})
        return {
            "views": int(st.get("viewCount", 0)),
            "likes": int(st.get("likeCount", 0)),
            "comments": int(st.get("commentCount", 0)),
        }

    # -- helpers -----------------------------------------------------------
    def _metadata(self, draft: Draft) -> tuple[str, str, list[str]]:
        first_line = (draft.caption or draft.topic).strip().splitlines()[0]
        title = first_line[:95]
        if self.yt.get("add_shorts_tag", True) and "#shorts" not in title.lower():
            title = f"{title} #Shorts"
        desc = draft.caption or ""
        if draft.hashtags:
            desc = f"{desc}\n\n{draft.hashtags}"
        if self.yt.get("add_shorts_tag", True) and "#shorts" not in desc.lower():
            desc += "\n#Shorts"
        tags = [t.lstrip("#") for t in draft.hashtag_list()]
        return title, desc, tags
