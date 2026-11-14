"""LexiScan API entrypoint: `uvicorn main:app --reload --port 5001`."""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import db
from app.api import mount
from app.config import CORS_ORIGINS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

db.init_db()

app = FastAPI(title="LexiScan API", version="2.0.0",
              description="Human-in-the-loop contract review built on LangGraph.")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)
mount(app)
