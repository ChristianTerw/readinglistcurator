"""
app.py
------
The web-facing part of the reading list curator.

- GET  /              -> shows the webpage with a text box
- POST /api/digest    -> takes an abstract, returns related papers as JSON

New concepts introduced:
- FastAPI: a Python framework for building web apps/APIs
- "decorators" like @app.get(...) - a way of labeling a function as
  "this runs when a request comes in for this URL"
- returning HTML directly vs. returning JSON
- basic JavaScript (fetch) on the frontend, calling our own API
"""

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv

from digest_logic import get_related_papers

load_dotenv()  # loads OPENALEX_API_KEY from .env when running locally

app = FastAPI()


# Pydantic models describe the "shape" of data we expect to receive
# or send back. FastAPI uses this to validate incoming requests
# automatically - if someone sends the wrong shape of data, FastAPI
# rejects it before our code even runs.
class AbstractRequest(BaseModel):
    abstract: str
    journal: str | None = None
    relevance_weight: float = 0.7


@app.get("/", response_class=HTMLResponse)
def home():
    """Serve the webpage itself."""
    return HTML_PAGE


@app.post("/api/digest")
def digest(request: AbstractRequest):
    """
    Receive an abstract (plus optional journal and relevance_weight),
    and return the top 10 related recent papers as JSON.
    """
    try:
        results = get_related_papers(
            request.abstract,
            journal=request.journal,
            relevance_weight=request.relevance_weight,
            limit=10,
        )
        return {"results": results}
    except Exception as e:
        # Instead of letting the server crash silently, send back a
        # clear error the frontend can actually show to the person.
        return JSONResponse(
            status_code=500,
            content={"error": f"Something went wrong while searching: {e}"},
        )


# The webpage itself, as one big HTML string. For a project this
# size, keeping it inline like this is simpler than separate files -
# we can always split it out later if it grows.
HTML_PAGE = """
<!DOCTYPE html>
<html>
<head>
    <title>Reading List Curator</title>
    <style>
        body { font-family: sans-serif; max-width: 700px; margin: 40px auto; padding: 0 20px; }
        textarea { width: 100%; height: 150px; font-family: inherit; font-size: 1em; padding: 10px; }
        button { padding: 10px 20px; font-size: 1em; cursor: pointer; margin-top: 10px; }
        .paper { margin-bottom: 20px; padding-bottom: 15px; border-bottom: 1px solid #ddd; }
        .paper a { font-weight: bold; text-decoration: none; color: #1a5fb4; }
        .meta { color: #666; font-size: 0.9em; }
        #status { color: #666; font-style: italic; }
    </style>
</head>
<body>
    <h1>Reading List Curator</h1>
    <p>Paste an abstract below to find related, recent papers.</p>

    <textarea id="abstractInput" placeholder="Paste an abstract here..."></textarea>
    <br>

    <label for="journalInput">Target journal (optional):</label><br>
    <input type="text" id="journalInput" placeholder="e.g. Nature, Management Science" style="width: 100%; padding: 8px; font-size: 1em;">
    <br><br>

    <label for="weightSlider">Prioritize: Recency &larr;&rarr; Relevance</label><br>
    <input type="range" id="weightSlider" min="0" max="1" step="0.1" value="0.7" style="width: 100%;">
    <div id="weightLabel" class="meta">Relevance weight: 0.7</div>
    <br>

    <button onclick="findRelatedPapers()">Find related papers</button>

    <p id="status"></p>
    <div id="results"></div>

    <script>
        // Update the little label live as the slider moves.
        const slider = document.getElementById('weightSlider');
        const weightLabel = document.getElementById('weightLabel');
        slider.addEventListener('input', () => {
            weightLabel.textContent = `Relevance weight: ${slider.value}`;
        });

        async function findRelatedPapers() {
            const abstract = document.getElementById('abstractInput').value;
            const journal = document.getElementById('journalInput').value;
            const relevanceWeight = parseFloat(slider.value);
            const status = document.getElementById('status');
            const results = document.getElementById('results');

            if (!abstract.trim()) {
                status.textContent = 'Please paste an abstract first.';
                return;
            }

            status.textContent = 'Searching...';
            results.innerHTML = '';

            let response;
            try {
                response = await fetch('/api/digest', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        abstract: abstract,
                        journal: journal || null,
                        relevance_weight: relevanceWeight
                    })
                });
            } catch (networkError) {
                // The request never even reached the server (e.g. no internet).
                status.textContent = 'Could not reach the server. Please check your connection and try again.';
                return;
            }

            const data = await response.json();

            if (!response.ok) {
                // The server responded, but with an error (e.g. our new try/except in app.py).
                status.textContent = data.error || 'Something went wrong. Please try again.';
                return;
            }

            status.textContent = '';

            if (data.results.length === 0) {
                status.textContent = 'No matches found' + (journal ? ` in "${journal}"` : '') + ' among the most relevant recent papers. Try removing the journal filter or broadening the abstract.';
                return;
            }

            data.results.forEach((paper, i) => {
                results.innerHTML += `
                    <div class="paper">
                        <div>${i + 1}. <a href="${paper.url}" target="_blank">${paper.title}</a></div>
                        <div class="meta">Published: ${paper.published} &middot; Relevance: ${paper.relevance_score?.toFixed(3)}</div>
                    </div>
                `;
            });
        }
    </script>
</body>
</html>
"""
