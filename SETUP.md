# ContextGraph AI Setup Guide

This file gives quick local setup steps for running Dodge AI end-to-end.

## 1) Prerequisites

- Python 3.11+
- Node.js 18+ and npm
- Git

## 2) Clone

```bash
git clone https://github.com/agnibha-2002/dodge_ai.git
cd dodge_ai
```

## 3) Backend setup

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create `backend/.env`:

```env
HUGGINGFACE_API_KEY=your_key_here
HUGGINGFACE_MODEL=meta-llama/Llama-3.1-8B-Instruct
HUGGINGFACE_API_URL=https://router.huggingface.co/v1/chat/completions
```

Run backend:

```bash
python3 -m uvicorn app.main:app --reload --port 8000
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

## 4) Frontend setup

Open a new terminal:

```bash
cd frontend
npm install
```

Create `frontend/.env`:

```env
VITE_API_BASE_URL=http://localhost:8000
```

Run frontend:

```bash
npm run dev
```

Open:

- http://localhost:5173

## 5) Verify core features

- Graph loads on home screen
- Chat can answer a sample query
- `New Chat` button resets chat + graph context

## 6) Optional: production build check

```bash
cd frontend
npm run build
```

