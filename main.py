import os
import re
import json
import sqlite3
from typing import List, Dict, Any
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import requests

app = FastAPI(title="Mobile AI Agent")

# SQLite Database Setup
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

# LLM Configuration
LLM_API_KEY = os.getenv("LLM_API_KEY", "").strip()
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
MODEL_NAME = os.getenv("MODEL_NAME", "llama-3.3-70b-versatile")

# Tools
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

def web_search(query: str) -> str:
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        res = requests.post("https://html.duckduckgo.com/html/", data={"q": query}, headers=headers, timeout=6)
        snippets = re.findall(r'<a class="result__snippet[^>]*>(.*?)</a>', res.text, re.DOTALL)
        clean_snippets = [re.sub(r'<[^>]+>', '', s).strip() for s in snippets[:3]]
        if clean_snippets:
            return "\n\n".join([f"Result {i+1}: {s}" for i, s in enumerate(clean_snippets)])
        return "No web results found."
    except Exception as e:
        return f"Search error: {e}"

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
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the live internet for recent facts",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"]
            }
        }
    }
]

@app.get("/", response_class=HTMLResponse)
async def home():
    file_path = os.path.join(os.path.dirname(__file__), "templates", "index.html")
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>index.html nahi mila</h1>"

class QueryRequest(BaseModel):
    message: str

@app.post("/api/chat")
async def chat(payload: QueryRequest):
    if not LLM_API_KEY:
        return {"response": "Error: Render par LLM_API_KEY set nahi hai."}

    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json"
    }
    messages = [
        {"role": "system", "content": "You are a helpful AI assistant. Answer the user clearly."},
        {"role": "user", "content": payload.message}
    ]

    try:
        for _ in range(4):
            body = {
                "model": MODEL_NAME,
                "messages": messages,
                "tools": TOOLS_SPEC,
                "tool_choice": "auto"
            }
            res = requests.post(f"{LLM_BASE_URL}/chat/completions", headers=headers, json=body, timeout=20)
            data = res.json()

            # Catch API errors directly
            if "error" in data:
                err_msg = data["error"].get("message", json.dumps(data["error"]))
                return {"response": f"Groq API Error: {err_msg}"}

            if "choices" not in data or not data["choices"]:
                return {"response": f"Unexpected Response: {data}"}

            choice = data["choices"][0]["message"]

            if not choice.get("tool_calls"):
                return {"response": choice.get("content", "No response content")}

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
                elif func_name == "web_search":
                    out = web_search(args.get("query", ""))
                else:
                    out = "Tool not found."

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": out
                })

        return {"response": "Agent step limit reached."}
    except Exception as e:
        return {"response": f"Server Error: {str(e)}"}
        
