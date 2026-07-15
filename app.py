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
from fastapi.responses import HTMLResponse
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


@app.get("/", response_class=HTMLResponse)
def home():
    """Serve the webpage itself."""
    return HTML_PAGE


@app.post("/api/digest")
def digest(request: AbstractRequest):
    """
    Receive an abstract (as JSON: {"abstract": "..."}), and return
    the top 10 related recent papers as JSON.
    """
    results = get_related_papers(request.abstract, limit=10)
    return {"results": results}


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
    <button onclick="findRelatedPapers()">Find related papers</button>

    <p id="status"></p>
    <div id="results"></div>

    <script>
        async function findRelatedPapers() {
            const abstract = document.getElementById('abstractInput').value;
            const status = document.getElementById('status');
            const results = document.getElementById('results');

            if (!abstract.trim()) {
                status.textContent = 'Please paste an abstract first.';
                return;
            }

            status.textContent = 'Searching...';
            results.innerHTML = '';

            // Send the abstract to our own /api/digest endpoint,
            // and wait for the response.
            const response = await fetch('/api/digest', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ abstract: abstract })
            });

            const data = await response.json();
            status.textContent = '';

            // Build the HTML for each paper and insert it into the page.
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
