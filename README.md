# BiteCheck

BiteCheck is a deep research chatbot for shoppers and readers who want to check claims about packaged food sold in the US and Europe. It compares ingredients and declared nutrition for equivalent products, looks up food-additive rules and scientific assessments, and links to the evidence behind each answer.

The Lead delegates to parallel researchers for product labels, regulations, and scientific evidence. It can request follow-up work before the Writer prepares the answer and the Citation Reviewer checks its support. The app uses Gemini on Vertex AI through LiteLLM, with Python orchestration and a FastAPI backend.

## Tools

| Tool | What it does |
| --- | --- |
| `research` | Delegates a focused question to a researcher with a separate context. |
| `finish_research` | Ends the Lead’s research loop and records unresolved gaps. |
| `search_sources` | Uses Google Search grounding to discover sources, then fetches candidate pages. |
| `read_source` | Reads a public web page, PDF, or JSON source and records its provenance. |
| `extract_label` | Extracts and normalizes a nutrition panel from a fetched label. |
| `normalize_label` | Checks manually extracted quantities against the cited label and converts them to a per-100 g or per-100 mL basis. |
| `inspect_label_coverage` | Shows which markets and nutrients have supporting labels and where more work is needed. |
| `read_label_image` | Transcribes a label image discovered on a fetched page and records uncertainty. |

Sources are discovered during each request. Depending on the question, they include manufacturer labels and linked images or PDFs, FDA publications, EFSA assessments, EU legislation via EUR-Lex, UK authorities, and relevant scientific studies. Open **Sources** or **Research activity** below an answer to see the pages retrieved. Missing label values stay unknown. A national label describes that market and product variant.

## How to use it

Type a question or choose one of the suggested questions. Name the product, variant, and markets when you know them. For a broad US–EU comparison, BiteCheck looks for comparable labels in EU markets with usable sources. The **Agent map** shows which researchers are working, and nutrition comparisons appear in the answer when suitable labels are available.

| Example query | What to look for |
| --- | --- |
| Compare Nutella Classic in the US, Germany and Italy. Does the Italian version have substantially less total sugar? | Compare total sugars per 100 g using Ferrero’s market-specific product labels. The earlier manufacturer-label check found roughly 56–57 g per 100 g in all three markets. |
| Compare the ingredients and sugar in regular Fanta Orange sold in the US and EU. Does the color difference prove that one version is safer? | Check local Coca-Cola labels for the exact variant. Compare sugars per 100 mL where declared and explain what color alone can establish. |
| Is titanium dioxide (E171) permitted as a food additive in the US and EU, and why do the rules differ? | Check FDA or federal rule text and EU legislation. Use EFSA’s assessment to explain the scientific basis and distinguish regulatory status from a health conclusion. |

### Sample runs

For each query, the baseline received only the user’s question with no system prompt or tools. The agent and baseline used the same Gemini Flash-Lite model. The saved runs include both full responses and the agent’s source links. They record what the agent found at the time of the run.

| Query | Baseline | BiteCheck |
| --- | --- | --- |
| [Nutella Classic](examples/nutella.json) | Reached the same broad conclusion on sugar and added uncited explanations about ingredient sourcing and taste. | Cited manufacturer labels and compared 56.8 g of total sugar per 100 g in the US with 56.3 g in Germany and Italy. |
| [Fanta Orange](examples/fanta.json) | Said color alone could not establish safety, but gave a broad European ingredient profile and no equal-volume sugar comparison. | Compared the retrieved US and German labels per 100 mL. It identified label differences and limited its findings to those markets. |
| [Titanium dioxide (E171)](examples/e171.json) | Identified the broad US–EU difference and gave a transition date without a citation. | Linked the US FDA position, the EU regulation, and EFSA’s assessment. It limited the comparison to US federal and EU rules. |

## Run locally

Install Python 3.11+, `uv`, and the Google Cloud CLI. Set `GOOGLE_CLOUD_PROJECT` in a copy of `.env.example` named `.env`. The project needs Vertex AI access.

```powershell
gcloud auth application-default login
uv sync --frozen
uv run --env-file .env app.py
```

Open [BiteCheck locally](http://127.0.0.1:8002/). The app uses live Vertex AI calls, which count toward your project’s usage.

## Checks

```powershell
uv run --locked -m unittest discover -s tests
node --test tests/*.test.cjs
```
