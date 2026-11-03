# AgentFlow AI v1.0

A personal AI-agent and workflow automation starter platform.

## Features
- Dark responsive dashboard
- Create, edit and delete agents
- Create and run workflows
- Workflow execution history
- AI chat endpoint using OpenAI (optional)
- SQLite persistence
- FastAPI backend with API key kept server-side

## Requirements
- Python 3.10+
- OpenAI API key (optional; set it only in backend `.env`)

## Run locally
```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Add OPENAI_API_KEY to .env if you want AI responses
uvicorn app.main:app --reload
```
Open http://127.0.0.1:8000

The frontend is served by FastAPI from `frontend/`. For phone-only development, edit files in GitHub and use a backend host that supports Python. GitHub Pages alone cannot run FastAPI.

## Security notes
- Never put your OpenAI API key in frontend JavaScript or commit `.env`.
- This starter runs only explicitly created workflows and does not execute arbitrary shell commands.
- Before exposing the app publicly, add authentication, HTTPS, rate limiting and per-user authorization.

## Current workflow actions
- `log`: records a message in the execution log
- `wait`: waits for a short duration (maximum 5 seconds)
- `ai`: asks the configured OpenAI model (requires API key)
