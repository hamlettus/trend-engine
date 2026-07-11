"""Google Trends source via pytrends (no API key required)."""
from __future__ import annotations

import datetime as dt

from trendengine.config import Config
from trendengine.sources.base import Source, TrendItem


class GoogleTrendsSource(Source):
    name = "google_trends"

    def fetch(self, keywords: list[str]) -> list[TrendItem]:
        from pytrends.request import TrendReq

        geo = self.settings.get("geo", "")
        timeframe = self.settings.get("timeframe", "now 7-d")
        pytrends = TrendReq(hl="en-US", tz=0)

        now = dt.datetime.now(dt.timezone.utc)
        items: list[TrendItem] = []

        # pytrends accepts up to 5 terms per payload.
        for batch_start in range(0, len(keywords), 5):
            batch = keywords[batch_start:batch_start + 5]
            pytrends.build_payload(batch, timeframe=timeframe, geo=geo)

            interest = pytrends.interest_over_time()
            # Current interest per keyword (last row), used as the raw score.
            for kw in batch:
                if interest is not None and not interest.empty and kw in interest.columns:
                    current = float(interest[kw].iloc[-1])
                else:
                    current = 0.0
                items.append(TrendItem(
                    source=self.name,
                    external_id=f"interest:{kw}",
                    title=f"Rising interest: {kw}",
                    url=f"https://trends.google.com/trends/explore?q={kw.replace(' ', '%20')}",
                    score=current,
                    created_at=now,
                    keyword=kw,
                    engagement={"interest": current},
                    extra={"kind": "interest_over_time", "timeframe": timeframe},
                ))

            # Related rising queries are strong "why now" signals.
            try:
                related = pytrends.related_queries()
                for kw in batch:
                    rising = (related.get(kw) or {}).get("rising")
                    if rising is None or rising.empty:
                        continue
                    for _, row in rising.head(5).iterrows():
                        query = str(row["query"])
                        value = float(row["value"])
                        items.append(TrendItem(
                            source=self.name,
                            external_id=f"rising:{kw}:{query}",
                            title=f"Breakout query: {query}",
                            url=f"https://trends.google.com/trends/explore?q={query.replace(' ', '%20')}",
                            score=value,
                            created_at=now,
                            keyword=kw,
                            engagement={"breakout_value": value},
                            extra={"kind": "rising_query", "seed": kw},
                        ))
            except Exception:  # noqa: BLE001 - related queries are best-effort
                pass
        return items
