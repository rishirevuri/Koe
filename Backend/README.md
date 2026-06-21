# Koe Backend

Koe Backend is the local prototype API for Koe, an AI inventory data-cleaning and counting system for restaurants. It preserves messy raw inputs while producing clean, structured inventory records that can be reviewed, approved, reported, and exported.

## Tech Stack

- Python
- FastAPI
- Uvicorn
- SQLAlchemy ORM
- SQLite at `data/koe.db`
- Pydantic
- Pytest

No external AI APIs, paid services, or API keys are used.

## Setup

```bash
cd /Users/ramarevuri/Documents/Koe/Backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m app.seed
uvicorn app.main:app --reload --port 8000
```

## Useful Commands

Health check:

```bash
curl http://127.0.0.1:8000/health
```

List inventory:

```bash
curl "http://127.0.0.1:8000/inventory/items?restaurant_id=1"
```

Create count session:

```bash
curl -X POST http://127.0.0.1:8000/counts \
  -H "Content-Type: application/json" \
  -d '{"restaurant_id":1,"area":"Dry Storage","notes":"Sunday night count"}'
```

Parse voice example:

```bash
curl -X POST http://127.0.0.1:8000/ai/parse-voice \
  -H "Content-Type: application/json" \
  -d '{"restaurant_id":1,"count_session_id":1,"text":"We have 3 bottles of olive oil, one of which is half empty, 3 heads of lettuce, 5 boxes of tomatoes, and 2 boxes of cheese.","area":"Dry Storage","save":true}'
```

Get JSON report:

```bash
curl http://127.0.0.1:8000/reports/1
```

Get CSV export:

```bash
curl -OJ http://127.0.0.1:8000/reports/1/csv
```

## Main Endpoints

- `GET /health`
- `POST /restaurants`
- `GET /restaurants`
- `GET /restaurants/{restaurant_id}`
- `POST /inventory/items`
- `GET /inventory/items?restaurant_id=1`
- `GET /inventory/items/{item_id}`
- `PUT /inventory/items/{item_id}`
- `DELETE /inventory/items/{item_id}`
- `POST /inventory/items/bulk`
- `POST /counts`
- `GET /counts?restaurant_id=1`
- `GET /counts/{count_id}`
- `POST /counts/{count_id}/entries`
- `GET /counts/{count_id}/entries`
- `PUT /counts/{count_id}/approve`
- `POST /ai/parse-voice`
- `POST /ai/parse-upload`
- `POST /ai/normalize-item`
- `GET /issues?restaurant_id=1`
- `GET /issues/{issue_id}`
- `PUT /issues/{issue_id}/resolve`
- `GET /reports/{count_id}`
- `GET /reports/{count_id}/csv`

## Tests

```bash
python -m compileall app
pytest
```

## Notes

This backend is deterministic by design. The AI-style routes use local parsing, normalization, matching, and issue creation logic. External LLM calls can be added later behind the service layer without changing the API shape.
