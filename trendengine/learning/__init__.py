"""The self-improvement loop: learn from the engine's own post performance.

Three cooperating pieces:
  * ThompsonBandit  — picks controllable knobs (post hour, caption style, hashtag
                      count) and learns which win from real engagement.
  * WeightLearner   — ridge-regresses engagement on topic features and feeds the
                      learned, bounded weights back into topic ranking.
  * PerformanceIngestor — pulls settled stats from the platform and closes the loop.
"""
from trendengine.learning.bandit import ThompsonBandit
from trendengine.learning.corpus import CorpusLearner
from trendengine.learning.ingest import PerformanceIngestor
from trendengine.learning.title_model import TitleModel
from trendengine.learning.weights import WeightLearner

__all__ = ["ThompsonBandit", "WeightLearner", "PerformanceIngestor",
           "CorpusLearner", "TitleModel"]
