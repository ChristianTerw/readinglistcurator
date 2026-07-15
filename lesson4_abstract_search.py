"""
Lesson 4: Paste an abstract, get related recent papers back
--------------------------------------------------------------
Goal: paste in the abstract of a paper (yours, or one you just
read), and get back a ranked list of recent, related papers.

Concepts introduced:
- input(), for reading text typed/pasted by the person running the script
- a "read until a sentinel value" loop, for multi-line input
- treating different-shaped inputs (a paper title vs. typed text) uniformly
- a dict used for deduplication (keyed by unique id)
"""

import requests
from datetime import date

API_KEY = "A3pUxivU4HSESb2k0ccrI6"

def read_abstract_from_file(filepath: str = "abstract.txt") -> str:
    """
    Read the abstract text out of a plain text file sitting in the
    same folder as this script.

    `with open(...) as f:` is Python's standard pattern for working
    with files - it opens the file, gives you `f` to read from, and
    automatically closes it again afterward (even if something goes
    wrong partway through), so you don't have to remember to do that
    yourself.
    """
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read().strip()


def get_paper_by_doi(doi: str) -> dict:
    """Look up a single work on OpenAlex using its DOI."""
    url = f"https://api.openalex.org/works/doi:{doi}"
    response = requests.get(url, params={"api_key": API_KEY})
    response.raise_for_status()
    return response.json()


def fetch_candidates(query_text: str) -> list:
    """
    Fetch up to 50 semantically related works published this year,
    for a single query string. (Same logic as Lesson 2's
    find_related_papers, minus the ranking step - we'll rank once,
    after combining candidates from all 5 seeds, not once per seed.)
    """
    current_year = date.today().year
    params = {
        "search.semantic": query_text,
        "filter": f"publication_year:{current_year}",
        "per-page": 50,
        "api_key": API_KEY,
    }

    response = requests.get("https://api.openalex.org/works", params=params)
    if not response.ok:
        print("OpenAlex said:", response.text)
    response.raise_for_status()
    return response.json()["results"]


def rank_by_relevance_and_recency(works: list, relevance_weight: float = 0.7) -> list:
    """Same ranking logic from Lesson 2."""
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


def build_digest(seed_dois: list, seed_interests: list, limit: int = 10) -> list:
    """
    Given a list of seed DOIs AND/OR a list of free-text interest
    descriptions, gather related candidates for all of them, merge
    and dedupe, then return one final ranked top-`limit` list.

    The key idea: a paper's title and a typed sentence are both just
    "text describing a topic" as far as fetch_candidates() is
    concerned. We turn everything into that common shape first
    (a list of query strings), then treat every entry identically.
    """
    # Step 1: look up the seed papers, so we can use their titles as
    # query text - and so we can exclude them from the final results
    # (no point recommending you a paper you already wrote).
    seed_papers = [get_paper_by_doi(doi) for doi in seed_dois]
    seed_ids = {paper["id"] for paper in seed_papers}

    # Step 2: build ONE combined list of query strings, regardless of
    # whether they came from a paper title or from your own typed
    # description. From here on, the code doesn't need to know which
    # is which.
    queries = [paper["display_name"] for paper in seed_papers] + seed_interests

    # Step 3: run every query, merging results into one dict keyed by
    # work id (this is what de-duplicates automatically - the same
    # paper showing up for two different queries just overwrites
    # itself at the same key instead of appearing twice).
    all_candidates = {}
    for query_text in queries:
        print(f"Searching for papers related to: {query_text}")
        candidates = fetch_candidates(query_text)

        for work in candidates:
            if work["id"] in seed_ids:
                continue  # don't recommend one of your own papers back to you
            all_candidates[work["id"]] = work

    print(f"\nFound {len(all_candidates)} unique candidate papers across {len(queries)} queries.\n")

    # Step 4: rank the combined, de-duplicated pool, and take the top N.
    combined = list(all_candidates.values())
    ranked = rank_by_relevance_and_recency(combined, relevance_weight=0.7)
    return ranked[:limit]


def main():
    abstract_text = read_abstract_from_file("abstract.txt")
    print(f"Read abstract ({len(abstract_text)} characters) from abstract.txt\n")

    # No paper DOIs this time - just the file's contents as our one query.
    digest = build_digest(seed_dois=[], seed_interests=[abstract_text], limit=10)

    # Build up the digest as one big string first...
    output_lines = ["=== Papers related to what you pasted ===\n"]
    for i, work in enumerate(digest, start=1):
        output_lines.append(f"{i}. {work['display_name']}")
        output_lines.append(f"   Published: {work.get('publication_date')}")
        output_lines.append(f"   Relevance score: {work.get('relevance_score')}")
        output_lines.append("")
    output_text = "\n".join(output_lines)

    # ...then write it to a file. "w" mode means "write" - it creates
    # the file if it doesn't exist yet, or overwrites it if it does.
    with open("digest.txt", "w", encoding="utf-8") as f:
        f.write(output_text)

    # Still print it too, so you can see it immediately without
    # having to open the file.
    print(output_text)
    print("(Also saved to digest.txt)")


if __name__ == "__main__":
    main()
