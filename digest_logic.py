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
from urllib.parse import urlencode

API_KEY = os.getenv("OPENALEX_API_KEY")

# Papers scoring below this on relevance get excluded entirely, rather
# than padding out the results just to reach 10. Chosen based on
# observed scores: genuinely on-topic matches tend to score 0.85+,
# while weak/loosely-related ones tend to fall below 0.80.
MIN_RELEVANCE = 0.80


def truncate_text(text: str, max_chars: int = 800) -> str:
    """
    Cut text down to at most max_chars, breaking at the last whole
    word rather than mid-word, so the query stays clean.

    Why 800, not something bigger: OpenAlex's semantic search is a
    GET request, meaning our query text becomes part of the URL
    itself. Spaces, commas, and other punctuation get "URL-encoded"
    into 3-character codes (a space becomes %20, a comma becomes
    %2C), so the encoded length can be noticeably longer than the
    raw text. OpenAlex enforces a hard 2,048-character URL limit
    across the whole request - so we keep the abstract itself well
    under that, leaving room for the rest of the URL (the base
    address, filters, and API key).
    """
    if len(text) <= max_chars:
        return text

    trimmed = text[:max_chars]
    last_space = trimmed.rfind(" ")  # find the last space before the cutoff
    if last_space != -1:
        trimmed = trimmed[:last_space]
    return trimmed


def fit_query_to_url_limit(query_text: str, other_params: dict, url_limit: int = 2000) -> str:
    """
    Shrink query_text, one word at a time, until the FULL encoded
    request URL (query text + all other params combined) fits under
    url_limit characters. This is more reliable than guessing a raw
    character count, since URL-encoding (spaces -> %20, commas ->
    %2C, etc.) can expand text by a different amount every time,
    depending on punctuation.
    """
    while True:
        params = dict(other_params)
        params["search.semantic"] = query_text
        full_url = "https://api.openalex.org/works?" + urlencode(params)

        if len(full_url) <= url_limit:
            return query_text

        words = query_text.rsplit(" ", 1)  # drop the last word and try again
        if len(words) == 1:
            return query_text  # can't shrink any further
        query_text = words[0]


def find_source_id(journal_name: str) -> str | None:
    """
    Look up a journal/venue by name and return its OpenAlex source ID
    (short form, e.g. "S137773608"), or None if nothing matches.

    This is needed because OpenAlex won't let us text-search for a
    journal by name in the same request as a semantic search - so we
    resolve the name to its exact ID first, in a separate, simple
    request, then use that ID (an exact match, not a text search).
    """
    params = {
        "search": journal_name,
        "per-page": 1,
        "api_key": API_KEY,
    }
    response = requests.get("https://api.openalex.org/sources", params=params)
    if not response.ok:
        raise ValueError(f"OpenAlex rejected the source lookup: {response.text}")

    results = response.json()["results"]
    if not results:
        return None

    full_id = results[0]["id"]  # e.g. "https://openalex.org/S137773608"
    return full_id.split("/")[-1]  # -> "S137773608"


def fetch_candidates(query_text: str, source_id: str = None) -> list:
    """
    Fetch up to 50 semantically related works published this year,
    for a single query string. Optionally restrict to an exact
    journal/venue, identified by its OpenAlex source ID.
    """
    current_year = date.today().year

    filters = [f"publication_year:{current_year}"]
    if source_id:
        filters.append(f"primary_location.source.id:{source_id}")

    base_params = {
        "filter": ",".join(filters),
        "per-page": 50,
        "api_key": API_KEY,
    }

    safe_query_text = fit_query_to_url_limit(query_text, base_params, url_limit=2000)

    params = dict(base_params)
    params["search.semantic"] = safe_query_text

    response = requests.get("https://api.openalex.org/works", params=params)
    if not response.ok:
        raise ValueError(f"OpenAlex rejected the request: {response.text}")
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


def get_related_papers(abstract_text: str, journal: str = None, relevance_weight: float = 0.7, limit: int = 10) -> list:
    """
    The main entry point: given an abstract, return the top `limit`
    related, recent papers, ranked by relevance + recency.

    - journal: optionally restrict results to a specific journal/venue.
    - relevance_weight: 0.0 (pure recency) to 1.0 (pure relevance).
    """
    safe_abstract = truncate_text(abstract_text)

    source_id = None
    if journal:
        source_id = find_source_id(journal)
        if source_id is None:
            # No journal by that name was found at all - rather than
            # silently searching everything, say so explicitly.
            return []

    candidates = fetch_candidates(safe_abstract, source_id=source_id)

    # Drop anything below our quality floor, rather than letting weak
    # matches pad the list out to 10.
    candidates = [w for w in candidates if (w.get("relevance_score") or 0) >= MIN_RELEVANCE]

    if not candidates:
        return []

    ranked = rank_by_relevance_and_recency(candidates, relevance_weight=relevance_weight)

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
