# SciDiploOntology — Instrument Annotation App

Multi-annotator review tool for AI governance instruments.

## Run locally

```bash
pip install -r requirements.txt
# Add DATABASE_URL to .streamlit/secrets.toml (see secrets.toml.example)
streamlit run app.py
```

## Deploy (Streamlit Community Cloud)

1. Push this repo to GitHub (private is fine)
2. Go to [share.streamlit.io](https://share.streamlit.io) → New app → select repo
3. Main file: `app.py`
4. In **Settings → Secrets**, add:
   ```toml
   DATABASE_URL = "postgresql://..."
   ```
5. Deploy and share the URL with annotators

## Annotator URL shortcut

Append `?annotator=XX` to pre-fill the initials field:
```
https://<your-app>.streamlit.app?annotator=JD
```

## Files

| File | Purpose |
|------|---------|
| `app.py` | Main Streamlit app |
| `db_utils.py` | DB connection, models, load/save helpers |
| `criteria_cache.json` | Pre-computed 8-criteria analysis (~1,019 instruments) |
| `requirements.txt` | Python dependencies |
| `.streamlit/secrets.toml.example` | Secrets template |

## Labels

- ✅ **Keep** — real, specific governance instrument; include in knowledge graph
- ❌ **Drop** — media report, generic phrase, or non-existent as formal doc
- 🔍 **Review** — uncertain; needs adjudication

See `RA_INSTRUCTIONS.md` (share separately with RAs) for full annotation guidelines.
