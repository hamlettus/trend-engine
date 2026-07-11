"""TikTok Content Posting API publisher — STUB (free, official route).

Left as a guided stub. To implement:
  1. Register an app at https://developers.tiktok.com/ and apply for the
     "Content Posting API" scope (video.publish / video.upload).
  2. Complete OAuth to obtain a user access token; put it in .env as
     TIKTOK_ACCESS_TOKEN.
  3. Posting flow (Direct Post):
       a) POST /v2/post/publish/video/init/   (initialise upload, get upload_url)
       b) PUT the video bytes to upload_url
       c) poll /v2/post/publish/status/fetch/ until published
     Captions/hashtags go in the init payload's post_info.
  4. Fill in `publish()` and, if desired, set publishing.default_publisher:
     tiktok. The dashboard still only calls publish() on your explicit click.

Note: TikTok has no official *image/text-only* feed post API; this route is for
video. Docs: https://developers.tiktok.com/doc/content-posting-api-get-started/
"""
from __future__ import annotations

from trendengine.config import Config
from trendengine.db.models import Draft
from trendengine.publishers.base import Publisher, PublishResult


class TikTokPublisher(Publisher):
    name = "tiktok"

    API_BASE = "https://open.tiktokapis.com/v2"

    def __init__(self, config: Config) -> None:
        super().__init__(config)
        self.access_token = Config.env("TIKTOK_ACCESS_TOKEN")

    def prepare(self, draft: Draft) -> PublishResult:
        from trendengine.publishers.assisted import AssistedPublisher
        return AssistedPublisher(self.config).prepare(draft)

    def publish(self, draft: Draft) -> PublishResult:  # noqa: D102
        # TODO(user): implement the init -> upload -> poll flow from the docstring.
        raise NotImplementedError(
            "TikTok publishing is a stub. See trendengine/publishers/tiktok.py "
            "for the exact steps to enable it.")
