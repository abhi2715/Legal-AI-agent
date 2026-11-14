FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# SQLite app data and LangGraph checkpoints. Mount a volume here to keep reviews across restarts.
ENV LEXISCAN_DATA_DIR=/data
VOLUME ["/data"]

EXPOSE 10000
# One worker: LangGraph checkpoints and run locks live in this process's SQLite files.
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-10000} --workers 1"]
