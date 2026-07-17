"""
digest_logic.py
----------------
The core "brain" of the reading list curator. Given an abstract,
produces two ranked lists:
  - "recent": papers from the last X years, ranked by relevance + recency
  - "seminal": papers (any age) ranked by how many citations they've
    picked up in just the last Y years - a signal of ongoing/renewed
    influence, not just "old and highly cited overall"
"""

import os
import requests
from datetime import date
from urllib.parse import urlencode

API_KEY = os.getenv("OPENALEX_API_KEY")

# Papers scoring below this on relevance get excluded entirely, rather
# than padding out the results just to reach the requested count.
MIN_RELEVANCE = 0.80


def truncate_text(text: str, max_chars: int = 800) -> str:
    """
    Cut text down to at most max_chars, breaking at the last whole
    word rather than mid-word. This is a coarse first pass; the real
    URL-length safety check happens in fit_query_to_url_limit below.
    """
    if len(text) <= max_chars:
        return text
    trimmed = text[:max_chars]
    last_space = trimmed.rfind(" ")
    if last_space != -1:
        trimmed = trimmed[:last_space]
    return trimmed


def fit_query_to_url_limit(query_text: str, other_params: dict, url_limit: int = 2000) -> str:
    """
    Shrink query_text, one word at a time, until the FULL encoded
    request URL fits under url_limit characters (OpenAlex enforces a
    hard 2,048-character limit on the whole request URL).
    """
    while True:
        params = dict(other_params)
        params["search.semantic"] = query_text
        full_url = "https://api.openalex.org/works?" + urlencode(params)
        if len(full_url) <= url_limit:
            return query_text
        words = query_text.rsplit(" ", 1)
        if len(words) == 1:
            return query_text
        query_text = words[0]


def find_source_id(journal_name: str) -> str | None:
    """
    Look up a journal/venue by name and return its OpenAlex source ID
    (short form, e.g. "S137773608"), or None if nothing matches.
    """
    params = {"search": journal_name, "per-page": 1, "api_key": API_KEY}
    response = requests.get("https://api.openalex.org/sources", params=params)
    if not response.ok:
        raise ValueError(f"OpenAlex rejected the source lookup: {response.text}")

    results = response.json()["results"]
    if not results:
        return None
    return results[0]["id"].split("/")[-1]


def fetch_candidates(query_text: str, source_id: str = None) -> list:
    """
    Fetch up to 50 semantically related works (any publication year -
    we deliberately don't restrict by year here, since we need both
    recent AND older "seminal" candidates from the same pool).
    Optionally restrict to an exact journal/venue via its source ID.
    """
    base_params = {"per-page": 50, "api_key": API_KEY}
    if source_id:
        base_params["filter"] = f"primary_location.source.id:{source_id}"

    safe_query_text = fit_query_to_url_limit(query_text, base_params, url_limit=2000)

    params = dict(base_params)
    params["search.semantic"] = safe_query_text

    response = requests.get("https://api.openalex.org/works", params=params)
    if not response.ok:
        raise ValueError(f"OpenAlex rejected the request: {response.text}")
    return response.json()["results"]


def rank_by_relevance_and_recency(works: list, relevance_weight: float = 0.7) -> list:
    """Re-sort works by a blended score of relevance and recency."""
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


def citations_in_last_n_years(work: dict, years: int) -> int:
    """
    Sum up citations a paper received in just the last `years` years,
    using OpenAlex's counts_by_year breakdown. This is what lets an
    older-but-still-influential paper qualify as "seminal", rather
    than just favoring whatever has the highest all-time citation
    count (which would just be "old", not necessarily "still relevant").

    Note: OpenAlex's counts_by_year typically only covers roughly the
    last 10 years, so requesting a larger window than that won't find
    more data than OpenAlex actually provides.
    """
    current_year = date.today().year
    cutoff_year = current_year - years + 1

    yearly_counts = work.get("counts_by_year") or []
    return sum(
        entry.get("cited_by_count", 0)
        for entry in yearly_counts
        if entry.get("year", 0) >= cutoff_year
    )


def extract_authors(work: dict) -> list:
    """Pull out a plain list of author names from a work's authorships."""
    authorships = work.get("authorships") or []
    return [
        a["author"]["display_name"]
        for a in authorships
        if a.get("author") and a["author"].get("display_name")
    ]


def extract_journal(work: dict) -> str | None:
    """Pull out the journal/venue name a work was published in."""
    location = work.get("primary_location") or {}
    source = location.get("source") or {}
    return source.get("display_name")


def build_result(work: dict, recent_citations: int = None) -> dict:
    """Build the dictionary shape the website displays for one paper."""
    result = {
        "title": work.get("display_name"),
        "authors": extract_authors(work),
        "journal": extract_journal(work),
        "published": work.get("publication_date"),
        "relevance_score": work.get("relevance_score"),
        "cited_by_count": work.get("cited_by_count"),
        "url": work.get("id"),
    }
    if recent_citations is not None:
        result["recent_citations"] = recent_citations
    return result


def get_related_papers(
    abstract_text: str,
    journal: str = None,
    relevance_weight: float = 0.7,
    num_results: int = 10,
    recent_years: int = 3,
    seminal_years: int = 5,
) -> dict:
    """
    Main entry point. Returns a dict with two lists:
      - "recent": top `num_results` papers from the last `recent_years`
        years, ranked by relevance + recency.
      - "seminal": top `num_results` papers (any age) ranked by
        citations received in the last `seminal_years` years.
    """
    safe_abstract = truncate_text(abstract_text)

    source_id = None
    if journal:
        source_id = find_source_id(journal)
        if source_id is None:
            return {"recent": [], "seminal": []}

    candidates = fetch_candidates(safe_abstract, source_id=source_id)
    candidates = [w for w in candidates if (w.get("relevance_score") or 0) >= MIN_RELEVANCE]

    if not candidates:
        return {"recent": [], "seminal": []}

    # --- Recent list ---
    current_year = date.today().year
    recent_cutoff_year = current_year - recent_years + 1
    recent_candidates = [
        w for w in candidates
        if w.get("publication_year") and w["publication_year"] >= recent_cutoff_year
    ]
    recent_ranked = rank_by_relevance_and_recency(recent_candidates, relevance_weight=relevance_weight)
    recent_results = [build_result(w) for w in recent_ranked[:num_results]]

    # --- Seminal list ---
    scored_for_seminal = [
        (citations_in_last_n_years(w, seminal_years), w) for w in candidates
    ]
    # Only keep papers that actually have SOME recent citation activity -
    # otherwise a brand-new paper with 0 citations would clutter the list.
    scored_for_seminal = [(score, w) for score, w in scored_for_seminal if score > 0]
    scored_for_seminal.sort(key=lambda pair: pair[0], reverse=True)
    seminal_results = [
        build_result(w, recent_citations=score)
        for score, w in scored_for_seminal[:num_results]
    ]

    return {"recent": recent_results, "seminal": seminal_results}
