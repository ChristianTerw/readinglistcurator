"""
digest_logic.py
----------------
The core "brain" of the reading list curator, with no web-serving
code in it at all - just pure functions that take an abstract and
return related papers. Keeping this separate from app.py means the
same logic could be reused by a script, a website, anything.
"""

import os
import requests
from datetime import date

API_KEY = os.getenv("OPENALEX_API_KEY")


def fetch_candidates(query_text: str) -> list:
    """
    Fetch up to 50 semantically related works published this year,
    for a single query string.
    """
    current_year = date.today().year
    params = {
        "search.semantic": query_text,
        "filter": f"publication_year:{current_year}",
        "per-page": 50,
        "api_key": API_KEY,
    }

    response = requests.get("https://api.openalex.org/works", params=params)
    response.raise_for_status()
    return response.json()["results"]


def rank_by_relevance_and_recency(works: list, relevance_weight: float = 0.7) -> list:
    """
    Re-sort works by a blended score of relevance and recency, both
    normalized to a 0-1 scale first since they're on different scales.
    """
    today = date.today()

    relevance_scores = [w.get("relevance_score") or 0 for w in works]
    days_old = [
        (today - date.fromisoformat(w["publication_date"])).days
        if w.get("publication_date") else 9999
        for w in works
    ]

    min_rel, max_rel = min(relevance_scores), max(relevance_scores)
    rel_range = (max_rel - min_rel) or 1

    min_days, max_days = min(days_old), max(days_old)
    days_range = (max_days - min_days) or 1

    scored = []
    for work, rel, days in zip(works, relevance_scores, days_old):
        norm_relevance = (rel - min_rel) / rel_range
        norm_recency = 1 - ((days - min_days) / days_range)
        combined = relevance_weight * norm_relevance + (1 - relevance_weight) * norm_recency
        scored.append((combined, work))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [work for score, work in scored]


def get_related_papers(abstract_text: str, limit: int = 10) -> list:
    """
    The main entry point: given an abstract, return the top `limit`
    related, recent papers, ranked by relevance + recency.
    """
    candidates = fetch_candidates(abstract_text)
    ranked = rank_by_relevance_and_recency(candidates, relevance_weight=0.7)

    # Trim down to just the fields the website actually needs to display.
    results = []
    for work in ranked[:limit]:
        results.append({
            "title": work.get("display_name"),
            "published": work.get("publication_date"),
            "relevance_score": work.get("relevance_score"),
            "url": work.get("id"),
        })
    return results
