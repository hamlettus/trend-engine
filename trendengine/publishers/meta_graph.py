"""Meta Graph API publisher — STUB for Instagram Business / Facebook Page.

This is the free, OFFICIAL route (no scraping). It is intentionally left as a
guided stub so you can wire it up with your own app + tokens when ready.

To implement:
  1. Create a Meta app (https://developers.facebook.com/), add the
     "Instagram Graph API" product, and connect an Instagram *Business* or
     *Creator* account linked to a Facebook Page.
  2. Get a long-lived User access token with permissions:
       instagram_basic, instagram_content_publish, pages_show_list,
       business_management
  3. Put these in .env:  META_ACCESS_TOKEN, IG_BUSINESS_ACCOUNT_ID
  4. Instagram image/video publishing is a TWO-STEP flow:
       a) POST /{ig-user-id}/media           (creates a media container; the
          image/video must be a PUBLIC URL Meta can fetch — host it somewhere)
       b) POST /{ig-user-id}/media_publish    (publishes the container id)
  5. Fill in `publish()` below and flip publishing.default_publisher if you
     want this to be the default. Even then, the dashboard only calls publish()
     on your explicit click.

Docs: https://developers.facebook.com/docs/instagram-api/guides/content-publishing
"""
from __future__ import annotations

from trendengine.config import Config
from trendengine.db.models import Draft
from trendengine.publishers.base import Publisher, PublishResult


class MetaGraphPublisher(Publisher):
    name = "meta_graph"

    GRAPH_BASE = "https://graph.facebook.com/v21.0"

    def __init__(self, config: Config) -> None:
        super().__init__(config)
        self.access_token = Config.env("META_ACCESS_TOKEN")
        self.ig_user_id = Config.env("IG_BUSINESS_ACCOUNT_ID")

    def prepare(self, draft: Draft) -> PublishResult:
        # Delegate the human-friendly prep to the assisted publisher so approved
        # drafts are always exported/copied even before you wire up the API.
        from trendengine.publishers.assisted import AssistedPublisher
        return AssistedPublisher(self.config).prepare(draft)

    def publish(self, draft: Draft) -> PublishResult:  # noqa: D102
        # TODO(user): implement the two-step Graph API publish flow described in
        # this module's docstring. Left unimplemented so nothing posts by default.
        raise NotImplementedError(
            "Meta Graph publishing is a stub. See trendengine/publishers/"
            "meta_graph.py for the exact steps to enable it.")
