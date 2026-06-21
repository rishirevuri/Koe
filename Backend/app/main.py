from fastapi import FastAPI

from app.database import create_db_and_tables
from app.routes import ai, counts, health, inventory, issues, reports, restaurants


app = FastAPI(title="Koe Backend", version="0.1.0")


@app.on_event("startup")
def on_startup() -> None:
    create_db_and_tables()


app.include_router(health.router)
app.include_router(restaurants.router)
app.include_router(inventory.router)
app.include_router(counts.router)
app.include_router(ai.router)
app.include_router(issues.router)
app.include_router(reports.router)
