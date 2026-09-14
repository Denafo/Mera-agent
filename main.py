import os
import json
import sqlite3
from typing import List, Dict, Any
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import requests

app = FastAPI(title="Mobile AI Agent")
templates = Jinja2Templates(directory="templates")

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
init_db()

LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
MODEL_NAME = os.getenv("MODEL_NAME", "llama-3.3-70b-versatile")

def run_calculator(expression: str) -> str:
    try:
        sanitized = "".join([c for c in expression if c in "0123456789+-*/(). "])
        return str(eval(sanitized, {"__builtins__": None}, {}))
    except Exception as e:
        return f"Error: {e}"

def save_note(key: str, value: str) -> str:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT OR REPLACE INTO notes (key, value) VALUES (?, ?)", (key, value))
    return f"Saved note '{key}' successfully."

def read_notes() -> str:
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("SELECT key, value FROM notes").fetchall()
    return json.dumps({k: v for k, v in rows})

TOOLS_SPEC = [
    {
        "type": "function",
        "function": {
            "name": "calculator",
            "description": "Calculate math expressions accurately",
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
            "description": "Store personal information or tasks in memory",
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
            "description": "Fetch all saved notes and memory",
            "parameters": {"type": "object", "properties": {}}
        }
    }
]

class QueryRequest(BaseModel):
    message: str

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/api/chat")
async def chat(payload: QueryRequest):
    if not LLM_API_KEY:
        return {"response": "Error: LLM_API_KEY set nahi hai server par."}

    headers = {"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"}
    messages = [
        {"role": "system", "content": "You are an autonomous AI Agent. Use tools whenever calculation or memory access is needed."},
        {"role": "user", "content": payload.message}
    ]

    for _ in range(3):
        body = {
            "model": MODEL_NAME,
            "messages": messages,
            "tools": TOOLS_SPEC,
            "tool_choice": "auto"
        }
        res = requests.post(f"{LLM_BASE_URL}/chat/completions", headers=headers, json=body).json()
        choice = res["choices"][0]["message"]

        if not choice.get("tool_calls"):
            return {"response": choice["content"]}

        messages.append(choice)
        for tool_call in choice["tool_calls"]:
            func_name = tool_call["function"]["name"]
            args = json.loads(tool_call["function"]["arguments"])
            
            if func_name == "calculator":
                out = run_calculator(args.get("expression", "0"))
            elif func_name == "save_note":
                out = save_note(args.get("key", ""), args.get("value", ""))
            elif func_name == "read_notes":
                out = read_notes()
            else:
                out = "Tool not found."

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "content": out
            })

    return {"response": "Agent step limit reached."}
          
