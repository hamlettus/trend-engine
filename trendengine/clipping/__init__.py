"""Clipping: turn AUTHORIZED long-form source video into short vertical clips.

For the paid-clipper model — you clip content you have permission to redistribute
(a clipping-program license, a direct creator arrangement, or your own videos).
The authorization gate in `campaign.py` enforces that nothing gets clipped without
a stated rights basis.
"""


class ClipError(RuntimeError):
    """Raised when clipping tooling fails or a source is unusable."""


from trendengine.clipping.campaign import (Campaign, CampaignError,  # noqa: E402
                                           UnauthorizedSource, get_campaign,
                                           load_campaigns)

__all__ = ["ClipError", "Campaign", "CampaignError", "UnauthorizedSource",
           "get_campaign", "load_campaigns"]
