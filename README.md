# LexiScan AI — Intelligent Contract Analysis Platform

Full-stack application for automated legal document analysis, contract Q&A, and clause understanding.

- **client/**: React + Vite + TypeScript SPA
- **server/**: Flask API serving ML/NLP endpoints (RoBERTa, T5)

## Quickstart

### Prerequisites

- Node.js 18+
- Python 3.10+

### Backend

```bash
cd server
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
gunicorn -b 127.0.0.1:5001 app:app --reload
```

### Frontend

```bash
cd client
cp .env.example .env
npm install
npm run dev
```

Open:

- Frontend: http://localhost:5173
- Backend: http://localhost:5001/questionsshort

## Key Features

- Contract upload + intelligent question answering
- Reading comprehension model (RoBERTa fine-tuned on CUAD)
- Paraphrasing (T5-based)
- Sentiment analysis (TextBlob)
- Real-time processing indicators
- Cited answers with source snippets

## Disclaimer

This project is provided for research/education and is **not** a substitute for professional legal advice.
