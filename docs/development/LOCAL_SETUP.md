# Local Developer Setup Guide

## 1. Prerequisites
- **Python**: Version 3.11 or 3.12
- **Node.js**: Version 18+ and npm
- **Git**
- Optional: PostgreSQL (SQLite is supported out-of-the-box as an automated fallback)

---

## 2. Step-by-Step Installation

### Clone the Repository
```bash
git clone -b develop https://github.com/Dhruv-vm/GoldSense-AI.git
cd GoldSense-AI
```

### Backend Virtual Environment & Dependencies
```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Frontend Dependencies
```bash
cd ../frontend
npm install
```

---

## 3. Launching Development Servers

### Start FastAPI Backend
```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
API Documentation will be live at `http://localhost:8000/docs`.

### Start Next.js Frontend Terminal
```bash
cd frontend
npm run dev
```
Open `http://localhost:3000` in your web browser.
