"""
app.py
------
The web-facing part of the reading list curator.

- GET  /              -> shows the webpage
- POST /api/digest    -> takes an abstract + settings, returns two
                          ranked lists of papers as JSON
"""

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv

from digest_logic import get_related_papers

load_dotenv()

app = FastAPI()


class AbstractRequest(BaseModel):
    abstract: str
    journal: str | None = None
    relevance_weight: float = 0.7
    num_results: int = 10
    recent_years: int = 3
    seminal_years: int = 5


@app.get("/", response_class=HTMLResponse)
def home():
    return HTML_PAGE


@app.post("/api/digest")
def digest(request: AbstractRequest):
    try:
        results = get_related_papers(
            request.abstract,
            journal=request.journal,
            relevance_weight=request.relevance_weight,
            num_results=request.num_results,
            recent_years=request.recent_years,
            seminal_years=request.seminal_years,
        )
        return results
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": f"Something went wrong while searching: {e}"},
        )


HTML_PAGE = """
<!DOCTYPE html>
<html>
<head>
    <title>Reading List Curator</title>
    <style>
        body { font-family: sans-serif; max-width: 750px; margin: 40px auto; padding: 0 20px; }
        textarea { width: 100%; height: 150px; font-family: inherit; font-size: 1em; padding: 10px; }
        input[type=text], input[type=number] { padding: 8px; font-size: 1em; }
        button { padding: 10px 20px; font-size: 1em; cursor: pointer; margin-top: 10px; }
        .row { display: flex; gap: 20px; margin: 15px 0; flex-wrap: wrap; }
        .field { display: flex; flex-direction: column; }
        .field label { margin-bottom: 4px; font-size: 0.9em; }
        h2 { border-bottom: 2px solid #1a5fb4; padding-bottom: 5px; margin-top: 40px; }
        .paper { margin-bottom: 20px; padding-bottom: 15px; border-bottom: 1px solid #ddd; }
        .paper a { font-weight: bold; text-decoration: none; color: #1a5fb4; }
        .meta { color: #666; font-size: 0.9em; }
        #status { color: #666; font-style: italic; }
    </style>
</head>
<body>
    <h1>Reading List Curator</h1>
    <p>Paste an abstract below to find related papers.</p>

    <textarea id="abstractInput" placeholder="Paste an abstract here..."></textarea>

    <div class="row">
        <div class="field">
            <label for="journalInput">Target journal (optional)</label>
            <input type="text" id="journalInput" placeholder="e.g. Nature">
        </div>
        <div class="field">
            <label for="numResultsInput"># of results per list</label>
            <input type="number" id="numResultsInput" value="10" min="1" max="50" style="width: 80px;">
        </div>
        <div class="field">
            <label for="recentYearsInput">"Recent" = last __ years</label>
            <input type="number" id="recentYearsInput" value="3" min="1" max="20" style="width: 80px;">
        </div>
        <div class="field">
            <label for="seminalYearsInput">"Seminal" = citations in last __ years</label>
            <input type="number" id="seminalYearsInput" value="5" min="1" max="20" style="width: 80px;">
        </div>
    </div>

    <label for="weightSlider">Recent list priority: Recency &larr;&rarr; Relevance</label><br>
    <input type="range" id="weightSlider" min="0" max="1" step="0.1" value="0.7" style="width: 100%;">
    <div id="weightLabel" class="meta">Relevance weight: 0.7</div>
    <br>

    <button onclick="findRelatedPapers()">Find related papers</button>

    <p id="status"></p>
    <div id="recentSection"></div>
    <div id="seminalSection"></div>

    <script>
        const slider = document.getElementById('weightSlider');
        const weightLabel = document.getElementById('weightLabel');
        slider.addEventListener('input', () => {
            weightLabel.textContent = `Relevance weight: ${slider.value}`;
        });

        function renderPaper(paper, i) {
            const authors = paper.authors && paper.authors.length
                ? paper.authors.join(', ')
                : 'Unknown authors';
            const citationNote = paper.recent_citations !== undefined
                ? ` &middot; ${paper.recent_citations} citations in the selected window`
                : '';
            return `
                <div class="paper">
                    <div>${i + 1}. <a href="${paper.url}" target="_blank">${paper.title}</a></div>
                    <div class="meta">${authors}</div>
                    <div class="meta">${paper.journal || 'Unknown journal'} &middot; Published: ${paper.published}</div>
                    <div class="meta">Relevance: ${paper.relevance_score?.toFixed(3)}${citationNote}</div>
                </div>
            `;
        }

        async function findRelatedPapers() {
            const abstract = document.getElementById('abstractInput').value;
            const journal = document.getElementById('journalInput').value;
            const relevanceWeight = parseFloat(slider.value);
            const numResults = parseInt(document.getElementById('numResultsInput').value);
            const recentYears = parseInt(document.getElementById('recentYearsInput').value);
            const seminalYears = parseInt(document.getElementById('seminalYearsInput').value);

            const status = document.getElementById('status');
            const recentSection = document.getElementById('recentSection');
            const seminalSection = document.getElementById('seminalSection');

            if (!abstract.trim()) {
                status.textContent = 'Please paste an abstract first.';
                return;
            }

            status.textContent = 'Searching...';
            recentSection.innerHTML = '';
            seminalSection.innerHTML = '';

            let response;
            try {
                response = await fetch('/api/digest', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        abstract: abstract,
                        journal: journal || null,
                        relevance_weight: relevanceWeight,
                        num_results: numResults,
                        recent_years: recentYears,
                        seminal_years: seminalYears
                    })
                });
            } catch (networkError) {
                status.textContent = 'Could not reach the server. Please check your connection and try again.';
                return;
            }

            const data = await response.json();

            if (!response.ok) {
                status.textContent = data.error || 'Something went wrong. Please try again.';
                return;
            }

            status.textContent = '';

            if (data.recent.length === 0 && data.seminal.length === 0) {
                status.textContent = 'No sufficiently relevant matches found. Try removing the journal filter or broadening the abstract.';
                return;
            }

            recentSection.innerHTML = `<h2>Recent papers (last ${recentYears} years)</h2>`
                + (data.recent.length
                    ? data.recent.map(renderPaper).join('')
                    : '<p class="meta">No matches in this time window.</p>');

            seminalSection.innerHTML = `<h2>Seminal papers (citations in last ${seminalYears} years)</h2>`
                + (data.seminal.length
                    ? data.seminal.map(renderPaper).join('')
                    : '<p class="meta">No papers with recent citation activity found.</p>');
        }
    </script>
</body>
</html>
"""
