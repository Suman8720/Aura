from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pathlib import Path
from dotenv import load_dotenv
import sqlite3, json, os, time, uuid
from datetime import datetime, timezone

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

BASE = Path(__file__).resolve().parents[2]
FRONTEND = BASE / "frontend"
load_dotenv(Path(__file__).resolve().parents[1] / ".env")
DB = Path(__file__).resolve().parents[1] / "agentflow.db"

app = FastAPI(title="AgentFlow AI", version="1.0.0")
app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")

def connect():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    with connect() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS agents(
          id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL,
          instructions TEXT NOT NULL, model TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS workflows(
          id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT DEFAULT '',
          steps TEXT NOT NULL, enabled INTEGER DEFAULT 1, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS runs(
          id TEXT PRIMARY KEY, workflow_id TEXT, workflow_name TEXT,
          status TEXT NOT NULL, log TEXT NOT NULL, created_at TEXT NOT NULL
        );
        """)
        if c.execute("SELECT COUNT(*) FROM agents").fetchone()[0] == 0:
            now = datetime.now(timezone.utc).isoformat()
            c.execute("INSERT INTO agents VALUES(?,?,?,?,?,?)",
                ("agent-assistant","Personal Assistant","General assistant",
                 "Help me organize tasks, explain ideas and plan my day.","gpt-4o-mini",now))
        if c.execute("SELECT COUNT(*) FROM workflows").fetchone()[0] == 0:
            now = datetime.now(timezone.utc).isoformat()
            steps = [{"type":"log","message":"AgentFlow is ready. Your workflow ran successfully."}]
            c.execute("INSERT INTO workflows VALUES(?,?,?,?,?,?)",
                ("workflow-welcome","Welcome workflow","A safe starter workflow.",json.dumps(steps),1,now))

init_db()

class AgentIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    role: str = Field(default="Personal assistant", max_length=100)
    instructions: str = Field(default="Be helpful and concise.", max_length=4000)
    model: str = "gpt-4o-mini"

class WorkflowIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=300)
    steps: list[dict] = Field(default_factory=list)

class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    agent_id: str | None = None

def rowdict(row):
    return dict(row) if row else None

@app.get("/")
def home():
    return FileResponse(FRONTEND / "index.html")

@app.get("/api/health")
def health():
    return {"ok": True, "ai_configured": bool(os.getenv("OPENAI_API_KEY"))}

@app.get("/api/overview")
def overview():
    with connect() as c:
        agents = c.execute("SELECT * FROM agents ORDER BY created_at DESC").fetchall()
        workflows = c.execute("SELECT * FROM workflows ORDER BY created_at DESC").fetchall()
        runs = c.execute("SELECT * FROM runs ORDER BY created_at DESC LIMIT 8").fetchall()
        total = c.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        successful = c.execute("SELECT COUNT(*) FROM runs WHERE status='success'").fetchone()[0]
    return {
        "agents":[rowdict(x) for x in agents],
        "workflows":[{**rowdict(x), "steps":json.loads(x["steps"])} for x in workflows],
        "runs":[{**rowdict(x), "log":json.loads(x["log"])} for x in runs],
        "stats":{"agents":len(agents),"workflows":len(workflows),"executions":total,
                 "success_rate":round(successful*100/total) if total else 100}
    }

@app.post("/api/agents")
def create_agent(data: AgentIn):
    aid, now = str(uuid.uuid4()), datetime.now(timezone.utc).isoformat()
    with connect() as c:
        c.execute("INSERT INTO agents VALUES(?,?,?,?,?,?)",
                  (aid,data.name,data.role,data.instructions,data.model,now))
    return {"id":aid,"message":"Agent created"}

@app.put("/api/agents/{agent_id}")
def update_agent(agent_id: str, data: AgentIn):
    with connect() as c:
        cur = c.execute("UPDATE agents SET name=?,role=?,instructions=?,model=? WHERE id=?",
            (data.name,data.role,data.instructions,data.model,agent_id))
        if not cur.rowcount: raise HTTPException(404,"Agent not found")
    return {"message":"Agent updated"}

@app.delete("/api/agents/{agent_id}")
def delete_agent(agent_id: str):
    with connect() as c:
        cur = c.execute("DELETE FROM agents WHERE id=?", (agent_id,))
        if not cur.rowcount: raise HTTPException(404,"Agent not found")
    return {"message":"Agent deleted"}

@app.post("/api/workflows")
def create_workflow(data: WorkflowIn):
    wid, now = str(uuid.uuid4()), datetime.now(timezone.utc).isoformat()
    for step in data.steps:
        if step.get("type") not in {"log","wait","ai"}:
            raise HTTPException(400,"Allowed step types: log, wait, ai")
    with connect() as c:
        c.execute("INSERT INTO workflows VALUES(?,?,?,?,?,?)",
            (wid,data.name,data.description,json.dumps(data.steps),1,now))
    return {"id":wid,"message":"Workflow created"}

@app.delete("/api/workflows/{workflow_id}")
def delete_workflow(workflow_id: str):
    with connect() as c:
        cur = c.execute("DELETE FROM workflows WHERE id=?", (workflow_id,))
        if not cur.rowcount: raise HTTPException(404,"Workflow not found")
    return {"message":"Workflow deleted"}

def ask_ai(prompt, system="You are a careful, helpful personal AI assistant."):
    key = os.getenv("OPENAI_API_KEY")
    if not key or OpenAI is None:
        raise HTTPException(503,"AI is not configured. Add OPENAI_API_KEY to backend/.env and restart.")
    client = OpenAI(api_key=key)
    response = client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL","gpt-4o-mini"),
        messages=[{"role":"system","content":system},{"role":"user","content":prompt}],
        temperature=0.4
    )
    return response.choices[0].message.content or ""

@app.post("/api/chat")
def chat(data: ChatIn):
    system = "You are a personal AI assistant. Be clear, practical and honest."
    if data.agent_id:
        with connect() as c:
            a = c.execute("SELECT * FROM agents WHERE id=?", (data.agent_id,)).fetchone()
        if not a: raise HTTPException(404,"Agent not found")
        system = f"Role: {a['role']}. Instructions: {a['instructions']}"
    return {"reply":ask_ai(data.message,system)}

@app.post("/api/workflows/{workflow_id}/run")
def run_workflow(workflow_id: str):
    with connect() as c:
        w = c.execute("SELECT * FROM workflows WHERE id=?", (workflow_id,)).fetchone()
    if not w: raise HTTPException(404,"Workflow not found")
    steps = json.loads(w["steps"])
    logs, status = [], "success"
    try:
        for i, step in enumerate(steps,1):
            kind = step.get("type")
            stamp = datetime.now().astimezone().strftime("%H:%M:%S")
            if kind == "log":
                message = str(step.get("message","Workflow step completed"))[:500]
                logs.append({"time":stamp,"message":message,"level":"info"})
            elif kind == "wait":
                seconds = max(0,min(int(step.get("seconds",1)),5))
                time.sleep(seconds)
                logs.append({"time":stamp,"message":f"Waited {seconds} second(s)","level":"info"})
            elif kind == "ai":
                answer = ask_ai(str(step.get("prompt","Summarize that this workflow ran."))[:3000])
                logs.append({"time":stamp,"message":answer[:1000],"level":"info"})
            else:
                raise ValueError(f"Unsupported step type: {kind}")
    except Exception as e:
        status = "failed"
        logs.append({"time":datetime.now().astimezone().strftime("%H:%M:%S"),
                     "message":str(e),"level":"error"})
    rid, now = str(uuid.uuid4()), datetime.now(timezone.utc).isoformat()
    with connect() as c:
        c.execute("INSERT INTO runs VALUES(?,?,?,?,?,?)",
            (rid,workflow_id,w["name"],status,json.dumps(logs),now))
    return {"id":rid,"status":status,"log":logs}

@app.get("/api/runs")
def get_runs():
    with connect() as c:
        rows = c.execute("SELECT * FROM runs ORDER BY created_at DESC LIMIT 100").fetchall()
    return [{**rowdict(r),"log":json.loads(r["log"])} for r in rows]
