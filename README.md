# Forensic Delay Analysis Toolkit

A Streamlit-based preliminary delay analysis automation system for Primavera P6 projects.

## Features

- **Module 0: Data Inventory** — Intake & revision overview across multiple XER exports
- **Module 1: DCMA 14-Point Assessment** — Automated schedule assessment scorecard
- **Module 3: Milestone Shift Tracker** — Milestone movement analysis across programme revisions
- **Module 5: Baseline Critical Path** — Planned critical path via backward driving-logic trace or float-based identification
- **Module 4: As-Planned vs As-Recorded** — Variance analysis by activity code or WBS level (up to 4 dimensions)

All analyses produce:
- Interactive charts and tables
- Editable AI narratives (Claude/OpenAI/Gemini via API)
- Publication-ready Excel reports with colour-coded findings and caveats

## Quick Start

### Local Development

```bash
# Clone the repo
git clone https://github.com/YOUR_USERNAME/delay-analysis-toolkit.git
cd delay-analysis-toolkit

# Set up virtual environment
python3 -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

# Install dependencies
pip install -r requirements.txt

# Run the app
streamlit run app.py
```

The app will open at `http://localhost:8501`.

### Sample Data

Sample Primavera P6 exports are included in the `sample/` directory:
- `Sample Baseline.xer` — 1,300-activity DAMAC tower baseline
- `Sample Update.xer` — Updated programme for shift tracking

## Configuration

### API Keys for AI Narratives

If you want to generate narratives using Claude, OpenAI, or Gemini:

**Local:**
Create `.streamlit/secrets.toml`:
```toml
ANTHROPIC_API_KEY = "sk-..."
OPENAI_API_KEY = "sk-..."
GOOGLE_API_KEY = "..."
```

**On Streamlit Cloud:**
1. Deploy the app first
2. Go to your app settings → Secrets
3. Paste the same config above

## Architecture

- `dcma/` — DCMA 14-point assessment engine (standalone, reusable)
- `programme/` — Programme-based modules:
  - `inventory.py` — Multi-revision intake
  - `milestones.py` — Milestone shift tracking
  - `critical_path.py` — Critical path extraction (longest-path & float methods)
  - `variance.py` — Group-based variance with multi-dimensional breakdown
  - `activity_codes.py`, `wbs.py` — Dimension helpers
  - `narrative.py` — Prompt builders for LLM narratives
  - `report_xlsx.py` — Excel workbook generation
- `app.py` — Streamlit UI (5 tabs, one per module)

**Design principle:** Deterministic Python engines → structured typed results → optional constrained LLM narrative.

## Deployment

### On Streamlit Cloud (Recommended)

1. Push code to GitHub
2. Go to [share.streamlit.io](https://share.streamlit.io)
3. Click "New app", select your repo, branch `main`, file `app.py`
4. Deploy

Free tier includes 1 app, sharing link, and automatic updates (push to GitHub = live).

### On Other Platforms

See `DEPLOYMENT.md` for instructions for Railway, Render, Heroku, or self-hosted.

## Testing

```bash
# Run unit tests
python test_programme.py
python test_engine.py
```

## Support

For issues, questions, or suggestions, please file an issue on GitHub.

---

**Built for forensic delay analysis in construction project controls.**
