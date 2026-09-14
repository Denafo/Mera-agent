import os
import re
import json
import sqlite3
from datetime import datetime
from typing import List, Dict, Any
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import requests

app = FastAPI(title="Mobile AI Agent Pro")

# SQLite Database Setup (Persistent Memory & Chat History)
DB_PATH = "agent_memory.db"

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE,
                value TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT,
                content TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
init_db()

# LLM Configuration
LLM_API_KEY = os.getenv("LLM_API_KEY", "").strip()
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")
CACHED_WORKING_MODEL = None

# ================= TOOLS =================

def run_calculator(expression: str) -> str:
    """Math calculator"""
    try:
        sanitized = "".join([c for c in expression if c in "0123456789+-*/(). "])
        return str(eval(sanitized, {"__builtins__": None}, {}))
    except Exception as e:
        return f"Calc Error: {e}"

def save_note(key: str, value: str) -> str:
    """Store persistent data"""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT OR REPLACE INTO notes (key, value) VALUES (?, ?)", (key, value))
    return f"Note '{key}' saved successfully."

def read_notes() -> str:
    """Retrieve saved notes"""
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("SELECT key, value FROM notes").fetchall()
    if not rows:
        return "Memory is currently empty."
    return json.dumps({k: v for k, v in rows})

def get_current_datetime() -> str:
    """Provides real-time date and time"""
    now = datetime.now()
    return now.strftime("%A, %d %B %Y, %I:%M:%S %p")

def web_search(query: str) -> str:
    """Live internet search via DuckDuckGo"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        res = requests.post("https://html.duckduckgo.com/html/", data={"q": query}, headers=headers, timeout=8)
        snippets = re.findall(r'<a class="result__snippet[^>]*>(.*?)</a>', res.text, re.DOTALL)
        clean = [re.sub(r'<[^>]+>', '', s).strip() for s in snippets[:3]]
        if clean:
            return "\n\n".join([f"Result {i+1}: {s}" for i, s in enumerate(clean)])
        return "No web results found."
    except Exception as e:
        return f"Search connection error: {e}"

TOOLS_SPEC = [
    {
        "type": "function",
        "function": {
            "name": "calculator",
            "description": "Perform mathematical calculations accurately.",
            "parameters": {
                "type": "object",
                "properties": {"expression": {"type": "string"}},
                "required": ["expression"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "save_note",
            "description": "Save reminders, personal preferences, or key information into persistent memory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "value": {"type": "string"}
                },
                "required": ["key", "value"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_notes",
            "description": "Read all saved notes and user information from database.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_datetime",
            "description": "Fetch current live system date, day, and time.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the live web for current facts, news, and live updates.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"]
            }
        }
    }
]

def resolve_model(headers: dict) -> List[str]:
    """Finds working chat models and prioritizes top models"""
    global CACHED_WORKING_MODEL
    if CACHED_WORKING_MODEL:
        return [CACHED_WORKING_MODEL]

    fallback_list = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "llama3-70b-8192", "mixtral-8x7b-32768"]
    try:
        res = requests.get(f"{LLM_BASE_URL}/models", headers=headers, timeout=5)
        if res.status_code == 200:
            data = res.json().get("data", [])
            valid = []
            for item in data:
                m = item.get("id", "")
                m_low = m.lower()
                if any(bad in m_low for bad in ["canopy", "orpheus", "whisper", "guard", "vision", "embed", "tts"]):
                    continue
                valid.append(m)
            ordered = [m for m in fallback_list if m in valid] + [m for m in valid if m not in fallback_list]
            return ordered if ordered else fallback_list
    except Exception:
        pass
    return fallback_list

# Database history helpers
def get_recent_history(limit: int = 6) -> List[Dict[str, str]]:
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("SELECT role, content FROM chat_history ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [{"role": r[0], "content": r[1]} for r in reversed(rows)]

def save_history(role: str, content: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT INTO chat_history (role, content) VALUES (?, ?)", (role, content))

@app.get("/", response_class=HTMLResponse)
async def home():
    file_path = os.path.join(os.path.dirname(__file__), "templates", "index.html")
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>index.html template missing</h1>"

class QueryRequest(BaseModel):
    message: str

@app.post("/api/chat")
async def chat(payload: QueryRequest):
    global CACHED_WORKING_MODEL
    if not LLM_API_KEY:
        return {"response": "Error: Render par LLM_API_KEY set nahi hai."}

    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json"
    }

    # Save user input to history
    save_history("user", payload.message)
    past_turns = get_recent_history(limit=6)

    candidate_models = resolve_model(headers)
    last_err = ""

    for model_name in candidate_models:
        messages = [
            {
                "role": "system", 
                "content": "You are a versatile, autonomous personal AI assistant. Proactively use tools whenever calculations, real-time facts, current time, or notes storage/retrieval are required. Answer concisely and clearly."
            }
        ] + past_turns

        try:
            success = False
            for _ in range(4):
                body = {
                    "model": model_name,
                    "messages": messages,
                    "tools": TOOLS_SPEC,
                    "tool_choice": "auto"
                }
                res = requests.post(f"{LLM_BASE_URL}/chat/completions", headers=headers, json=body, timeout=25)
                data = res.json()

                if "error" in data:
                    last_err = data["error"].get("message", "Unknown error")
                    break

                if "choices" not in data or not data["choices"]:
                    break

                choice = data["choices"][0]["message"]

                if not choice.get("tool_calls"):
                    reply = choice.get("content", "")
                    save_history("assistant", reply)
                    CACHED_WORKING_MODEL = model_name  # Cache working model for future calls
                    return {"response": reply}

                messages.append(choice)
                for tc in choice["tool_calls"]:
                    f_name = tc["function"]["name"]
                    args = json.loads(tc["function"]["arguments"])

                    if f_name == "calculator":
                        tool_res = run_calculator(args.get("expression", "0"))
                    elif f_name == "save_note":
                        tool_res = save_note(args.get("key", ""), args.get("value", ""))
                    elif f_name == "read_notes":
                        tool_res = read_notes()
                    elif f_name == "get_current_datetime":
                        tool_res = get_current_datetime()
                    elif f_name == "web_search":
                        tool_res = web_search(args.get("query", ""))
                    else:
                        tool_res = "Tool error: Not implemented."

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": tool_res
                    })

        except Exception as e:
            last_err = str(e)
            continue

    return {"response": f"Service busy or model error: {last_err}"}
    
