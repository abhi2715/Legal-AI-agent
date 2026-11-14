"""Loaded automatically when the server is started with gunicorn from this directory.

FastAPI is ASGI, so gunicorn must use the uvicorn worker. Keep a single worker: LangGraph
checkpoints and per-thread run locks live in this process and its SQLite files.
"""
import os

worker_class = "uvicorn_worker.UvicornWorker"
workers = 1
bind = f"0.0.0.0:{os.getenv('PORT', '10000')}"
timeout = 180
graceful_timeout = 30
keepalive = 75
