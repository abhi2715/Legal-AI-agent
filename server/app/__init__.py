"""LexiScan backend package.

`app.app` resolves to the ASGI application in main.py, so a Render service still configured with the old
Flask start command (`gunicorn app:app`) keeps working; gunicorn.conf.py switches it to the uvicorn worker.
"""


def __getattr__(name):
    if name == "app":
        import main

        return main.app
    raise AttributeError(name)
