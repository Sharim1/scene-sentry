"""
Content Re-Ranking Agent — LangGraph state machine that scores Content rows
against a user's taste profile and persists UserContentRank records.

Nodes
-----
1. build_taste_profile  (no LLM)
2. select_candidates    (no LLM, pure SQL)
3. batch_score          (Gemini LLM — only AI node)
4. write_rankings       (no LLM)
5. validate_quality     (conditional → loops back or finishes)
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal, TypedDict

from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from app.models import Content, LibraryItem
from app.models.ranking import UserContentRank
from app.repositories.ranking_repo import RankingRepository

if TYPE_CHECKING:
    from app.agents import SessionFactory

logger = logging.getLogger(__name__)

BATCH_SIZE = 20
CANDIDATE_POOL = 50
MIN_RANKED_TARGET = 15
MIN_GENRE_DIVERSITY = 3
STALE_HOURS = 24


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


class RankingState(TypedDict):
    user_id: int
    taste_profile: dict[str, Any]
    candidates: list[dict[str, Any]]
    scored_items: list[dict[str, Any]]
    iteration: int
    max_iterations: int
    total_ranked: int


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------


class ContentRankingGraph:
    """Five-node LangGraph state machine for content re-ranking."""

    def __init__(self, session_factory: SessionFactory | None = None):
        from app.database import db_session

        self._session_factory = session_factory or db_session
        self._llm = None
        self._graph = None
        self._memory = MemorySaver()

    # -- lazy initialisers ---------------------------------------------------

    @property
    def llm(self) -> ChatGoogleGenerativeAI | None:
        if self._llm is None:
            self._llm = self._init_llm()
        return self._llm

    @property
    def graph(self):
        if self._graph is None:
            self._graph = self._build_graph()
        return self._graph

    @staticmethod
    def _init_llm() -> ChatGoogleGenerativeAI | None:
        from app.config import settings

        api_key = settings.gemini_api_key
        if not api_key:
            logger.warning("GEMINI_API_KEY not set — batch_score will fall back to heuristic scoring")
            return None

        return ChatGoogleGenerativeAI(
            model="gemini-2.0-flash-exp",
            google_api_key=api_key,
            temperature=0.3,
            max_output_tokens=4096,
        )

    # -- graph construction --------------------------------------------------

    def _build_graph(self) -> StateGraph:
        workflow = StateGraph(RankingState)

        workflow.add_node("build_taste_profile", self.build_taste_profile)
        workflow.add_node("select_candidates", self.select_candidates)
        workflow.add_node("batch_score", self.batch_score)
        workflow.add_node("write_rankings", self.write_rankings)
        workflow.add_node("validate_quality", self.validate_quality)

        workflow.set_entry_point("build_taste_profile")
        workflow.add_edge("build_taste_profile", "select_candidates")
        workflow.add_edge("select_candidates", "batch_score")
        workflow.add_edge("batch_score", "write_rankings")
        workflow.add_edge("write_rankings", "validate_quality")

        workflow.add_conditional_edges(
            "validate_quality",
            self._should_continue,
            {"loop": "select_candidates", "finish": END},
        )

        return workflow.compile(checkpointer=self._memory)

    # -----------------------------------------------------------------------
    # Node 1 — build_taste_profile (no LLM)
    # -----------------------------------------------------------------------

    async def build_taste_profile(self, state: RankingState) -> dict:
        user_id = state["user_id"]
        logger.info("[build_taste_profile] user=%s", user_id)

        profile: dict[str, Any] = {
            "genre_freq": {},
            "avg_rating_by_genre": {},
            "content_type_ratio": {},
            "top_genres": [],
        }

        try:
            with self._session_factory() as db:
                items = (
                    db.query(LibraryItem, Content)
                    .join(Content, LibraryItem.content_id == Content.id)
                    .filter(LibraryItem.user_id == user_id)
                    .all()
                )

                if not items:
                    logger.warning("[build_taste_profile] user %s has no library items", user_id)
                    return {"taste_profile": profile}

                genre_counter: Counter = Counter()
                genre_rating_sums: dict[str, float] = {}
                genre_rating_counts: dict[str, int] = {}
                type_counter: Counter = Counter()

                for lib_item, content in items:
                    type_counter[content.content_type] += 1

                    genres = _parse_genres(content.genres)
                    for g in genres:
                        genre_counter[g] += 1
                        if lib_item.rating:
                            genre_rating_sums[g] = genre_rating_sums.get(g, 0.0) + lib_item.rating
                            genre_rating_counts[g] = genre_rating_counts.get(g, 0) + 1

                total_items = len(items)
                profile["genre_freq"] = {g: round(c / total_items, 3) for g, c in genre_counter.most_common()}
                profile["avg_rating_by_genre"] = {
                    g: round(genre_rating_sums[g] / genre_rating_counts[g], 2) for g in genre_rating_sums
                }
                profile["content_type_ratio"] = {t: round(c / total_items, 3) for t, c in type_counter.items()}
                profile["top_genres"] = [
                    g
                    for g, _ in sorted(
                        profile["avg_rating_by_genre"].items(),
                        key=lambda kv: kv[1],
                        reverse=True,
                    )
                ][:10]

        except Exception:
            logger.exception("[build_taste_profile] failed for user %s", user_id)

        return {"taste_profile": profile}

    # -----------------------------------------------------------------------
    # Node 2 — select_candidates (no LLM, pure SQL)
    # -----------------------------------------------------------------------

    async def select_candidates(self, state: RankingState) -> dict:
        user_id = state["user_id"]
        top_genres = state["taste_profile"].get("top_genres", [])
        logger.info("[select_candidates] user=%s top_genres=%s", user_id, top_genres[:5])

        candidates: list[dict[str, Any]] = []

        try:
            with self._session_factory() as db:
                library_ids = db.query(LibraryItem.content_id).filter(LibraryItem.user_id == user_id).subquery()

                freshness_cutoff = datetime.now(UTC) - timedelta(hours=STALE_HOURS)
                fresh_ranked_ids = (
                    db.query(UserContentRank.content_id)
                    .filter(
                        UserContentRank.user_id == user_id,
                        UserContentRank.ranked_at >= freshness_cutoff,
                    )
                    .subquery()
                )

                query = db.query(Content).filter(
                    ~Content.id.in_(library_ids),
                    ~Content.id.in_(fresh_ranked_ids),
                )

                if top_genres:
                    genre_filters = [Content.genres.ilike(f"%{g}%") for g in top_genres[:5]]
                    from sqlalchemy import or_

                    query = query.filter(or_(*genre_filters))

                rows = query.order_by(Content.rating.desc().nullslast()).limit(CANDIDATE_POOL).all()

                for c in rows:
                    candidates.append(
                        {
                            "content_id": c.id,
                            "title": c.title,
                            "content_type": c.content_type,
                            "genres": _parse_genres(c.genres),
                            "rating": c.rating,
                            "description": (c.description or "")[:300],
                        }
                    )

        except Exception:
            logger.exception("[select_candidates] failed for user %s", user_id)

        logger.info("[select_candidates] found %d candidates", len(candidates))
        return {"candidates": candidates}

    # -----------------------------------------------------------------------
    # Node 3 — batch_score (Gemini LLM)
    # -----------------------------------------------------------------------

    async def batch_score(self, state: RankingState) -> dict:
        candidates = state["candidates"]
        taste = state["taste_profile"]
        logger.info("[batch_score] scoring %d candidates", len(candidates))

        if not candidates:
            return {"scored_items": []}

        all_scored: list[dict[str, Any]] = []

        batches = [candidates[i : i + BATCH_SIZE] for i in range(0, len(candidates), BATCH_SIZE)]

        for batch_idx, batch in enumerate(batches):
            try:
                scored = await self._score_batch(taste, batch, batch_idx)
                all_scored.extend(scored)
            except Exception:
                logger.exception("[batch_score] batch %d failed — falling back to heuristic", batch_idx)
                all_scored.extend(self._heuristic_score(taste, batch))

        logger.info("[batch_score] scored %d items total", len(all_scored))
        return {"scored_items": state.get("scored_items", []) + all_scored}

    async def _score_batch(
        self,
        taste: dict[str, Any],
        batch: list[dict[str, Any]],
        batch_idx: int,
    ) -> list[dict[str, Any]]:
        if self.llm is None:
            return self._heuristic_score(taste, batch)

        compact_candidates = [
            {
                "content_id": c["content_id"],
                "title": c["title"],
                "type": c["content_type"],
                "genres": c["genres"],
                "rating": c["rating"],
                "desc": c["description"][:200],
            }
            for c in batch
        ]

        prompt = (
            "You are a content recommendation scoring engine.\n\n"
            f"USER TASTE PROFILE:\n{json.dumps(taste, indent=2)}\n\n"
            f"CANDIDATE CONTENT (batch {batch_idx + 1}):\n{json.dumps(compact_candidates, indent=2)}\n\n"
            "Score each candidate from 0 to 100 based on how well it matches the "
            "user's taste profile. Consider genre overlap, content type preference, "
            "and how well-rated similar genres are.\n\n"
            "Return ONLY a JSON array — no markdown fences, no extra text:\n"
            '[{"content_id": <int>, "score": <0-100>, "reasoning": "<1 sentence>"}]'
        )

        response = await self.llm.ainvoke([HumanMessage(content=prompt)])
        return _parse_score_response(response.content, batch)

    @staticmethod
    def _heuristic_score(taste: dict[str, Any], batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Deterministic fallback when the LLM is unavailable."""
        avg_by_genre = taste.get("avg_rating_by_genre", {})
        genre_freq = taste.get("genre_freq", {})
        results = []
        for c in batch:
            genre_score = 0.0
            matched = 0
            for g in c.get("genres", []):
                if g in avg_by_genre:
                    genre_score += avg_by_genre[g] * genre_freq.get(g, 0.1)
                    matched += 1
            if matched:
                genre_score /= matched
            base = min((c.get("rating") or 5.0) * 10, 100)
            score = round(0.5 * base + 0.5 * genre_score * 20, 1)
            score = max(0, min(100, score))
            results.append(
                {
                    "content_id": c["content_id"],
                    "score": score,
                    "reasoning": "Heuristic: genre affinity + public rating",
                }
            )
        return results

    # -----------------------------------------------------------------------
    # Node 4 — write_rankings (no LLM)
    # -----------------------------------------------------------------------

    async def write_rankings(self, state: RankingState) -> dict:
        scored = state["scored_items"]
        user_id = state["user_id"]
        logger.info("[write_rankings] persisting %d scores for user %s", len(scored), user_id)

        written = 0
        try:
            with self._session_factory() as db:
                repo = RankingRepository(db)
                for item in scored:
                    try:
                        repo.upsert_rank(
                            user_id=user_id,
                            content_id=item["content_id"],
                            score=item["score"],
                            reasoning=item.get("reasoning"),
                        )
                        written += 1
                    except Exception:
                        logger.warning(
                            "[write_rankings] skip content_id=%s",
                            item.get("content_id"),
                            exc_info=True,
                        )
        except Exception:
            logger.exception("[write_rankings] transaction failed for user %s", user_id)

        new_total = state["total_ranked"] + written
        logger.info("[write_rankings] wrote %d, cumulative total=%d", written, new_total)
        return {"total_ranked": new_total, "iteration": state["iteration"] + 1}

    # -----------------------------------------------------------------------
    # Node 5 — validate_quality
    # -----------------------------------------------------------------------

    async def validate_quality(self, state: RankingState) -> dict:
        total = state["total_ranked"]
        scored = state["scored_items"]

        genres_seen: set = set()
        for item in scored:
            for c in state["candidates"]:
                if c["content_id"] == item["content_id"]:
                    genres_seen.update(c.get("genres", []))
                    break

        logger.info(
            "[validate_quality] iteration=%d total_ranked=%d genre_diversity=%d",
            state["iteration"],
            total,
            len(genres_seen),
        )
        return {"taste_profile": {**state["taste_profile"], "_genres_seen": list(genres_seen)}}

    # -- routing decision ----------------------------------------------------

    @staticmethod
    def _should_continue(state: RankingState) -> Literal["loop", "finish"]:
        if state["iteration"] >= state["max_iterations"]:
            return "finish"

        if state["total_ranked"] < MIN_RANKED_TARGET:
            genres_seen = set(state["taste_profile"].get("_genres_seen", []))
            if len(genres_seen) < MIN_GENRE_DIVERSITY:
                return "loop"
            if state["total_ranked"] < MIN_RANKED_TARGET // 2:
                return "loop"

        return "finish"

    # -----------------------------------------------------------------------
    # Public entry point
    # -----------------------------------------------------------------------

    async def run_ranking(self, user_id: int) -> list[dict[str, Any]]:
        """Execute the full ranking pipeline for *user_id* and return scored items."""
        initial_state: RankingState = {
            "user_id": user_id,
            "taste_profile": {},
            "candidates": [],
            "scored_items": [],
            "iteration": 0,
            "max_iterations": 3,
            "total_ranked": 0,
        }

        thread_id = f"rank_{user_id}_{datetime.now(UTC).isoformat()}"
        config = {"configurable": {"thread_id": thread_id}}

        try:
            final = await self.graph.ainvoke(initial_state, config=config)
            logger.info(
                "Ranking complete for user %s — %d items scored across %d iteration(s)",
                user_id,
                final["total_ranked"],
                final["iteration"],
            )
            return final["scored_items"]
        except Exception:
            logger.exception("Ranking pipeline failed for user %s", user_id)
            return []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_genres(raw: str | None) -> list[str]:
    """Safely extract a list of genre strings from the Content.genres column."""
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(g).strip() for g in parsed if g]
    except (json.JSONDecodeError, TypeError):
        return [g.strip() for g in raw.split(",") if g.strip()]
    return []


def _parse_score_response(
    text: str,
    batch: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Best-effort extraction of the JSON array from the LLM response."""
    cleaned = text.strip()
    if "```" in cleaned:
        start = cleaned.find("```")
        lang_end = cleaned.find("\n", start)
        end = cleaned.find("```", lang_end + 1)
        if end != -1:
            cleaned = cleaned[lang_end + 1 : end].strip()

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("[_parse_score_response] JSON decode failed, returning empty")
        return []

    if not isinstance(parsed, list):
        return []

    valid_ids = {c["content_id"] for c in batch}
    results = []
    for entry in parsed:
        cid = entry.get("content_id")
        if cid not in valid_ids:
            continue
        score = entry.get("score", 50)
        score = max(0, min(100, float(score)))
        results.append(
            {
                "content_id": cid,
                "score": score,
                "reasoning": str(entry.get("reasoning", ""))[:500],
            }
        )
    return results


# ---------------------------------------------------------------------------
# Module-level lazy singleton
# ---------------------------------------------------------------------------

ranking_graph = ContentRankingGraph()
