# Koe
<<<<<<< HEAD

Koe is an AI inventory data-cleaning and counting system for restaurants. It helps staff count inventory faster with voice, uploads, photos, and manual input, while preserving messy raw inputs and turning them into clean, consistent, analyzable inventory records.

## Current State

- `Frontend/`: static landing page for Koe.
- `Backend/`: FastAPI prototype backend with deterministic local parsing, normalization, partial quantity handling, review issues, JSON reports, and CSV export.

The backend does not require real API keys today. External AI, speech-to-text, vision, Google Sheets, Supabase, and Stripe integrations are represented by placeholders only.

## Run Frontend

```bash
cd /Users/ramarevuri/Documents/Koe/Frontend
npm run dev
```

Open `http://127.0.0.1:5174/`.

## Run Backend

```bash
cd /Users/ramarevuri/Documents/Koe/Backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m app.seed
uvicorn app.main:app --reload --port 8000
```

Open `http://127.0.0.1:8000/health`.

## Seed Backend Database

```bash
cd /Users/ramarevuri/Documents/Koe/Backend
source .venv/bin/activate
python -m app.seed
```

This resets local demo data in `Backend/data/koe.db`.

## Test Backend

```bash
cd /Users/ramarevuri/Documents/Koe/Backend
source .venv/bin/activate
python -m compileall app
pytest
```

## API Keys Later

Copy `.env.example` to `.env` at the repo root or copy `Backend/.env.example` to `Backend/.env` for backend-specific settings. Add real keys only when you are ready to enable integrations.

External integrations remain off unless:

```env
ENABLE_EXTERNAL_AI=true
```

## Current Limitations

- No authentication, payments, production database, or cloud deployment yet.
- No real external AI, speech-to-text, vision, Google Sheets, Supabase, Stripe, Toast, or Square calls yet.
- Parsing is deterministic and intentionally scoped to common local prototype cases.
=======
An AI inventory assistant that lets restaurant staff count inventory by voice and photo, then standardizes the data into clean, consistent records for spreadsheets or existing inventory systems.
>>>>>>> b097e1661c3f7e351b66c2210b903e765135dc10
