import os
import re
import ast
import json
import base64
import sqlite3
from datetime import datetime
from typing import List, Dict, Any
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import requests

app = FastAPI(title="DEMOR Autonomous Operating System")

DB_PATH = "agent_memory.db"

# ================= DATABASE ENGINE =================

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE,
                value TEXT,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS behavioral_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rule TEXT UNIQUE,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
init_db()

# LLM & GitHub Environment Configuration
LLM_API_KEY = os.getenv("LLM_API_KEY", "").strip()
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
GITHUB_REPO = os.getenv("GITHUB_REPO", "Denafo/Mera-agent").strip()
CACHED_WORKING_MODEL = None

# ================= CORE AGENT TOOLS =================

def run_calculator(expression: str) -> str:
    """Math calculator"""
    try:
        sanitized = "".join([c for c in expression if c in "0123456789+-*/(). "])
        return str(eval(sanitized, {"__builtins__": None}, {}))
    except Exception as e:
        return f"Calculation Error: {e}"

def save_note(key: str, value: str) -> str:
    """Stores user information/notes"""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO notes (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
            (key, value)
        )
    return f"Note '{key}' saved successfully."

def read_notes() -> str:
    """Reads all stored user memories"""
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("SELECT key, value FROM notes").fetchall()
    return json.dumps({k: v for k, v in rows}) if rows else "Memory storage is empty."

def learn_behavior_rule(rule: str) -> str:
    """Saves creator corrections and behavioural rules permanently"""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT OR IGNORE INTO behavioral_rules (rule) VALUES (?)", (rule.strip(),))
    return f"Naya rule successfully save ho gaya: '{rule}'"

def get_behavior_rules() -> str:
    """Loads all saved feedback rules into system prompt"""
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("SELECT rule FROM behavioral_rules").fetchall()
    if not rows:
        return ""
    rules_text = "\n".join([f"- {r[0]}" for r in rows])
    return f"\n[Boss ke dwara sikhaye gaye niyam jinka sakhti se palan karna hai]:\n{rules_text}\n"

def get_current_datetime() -> str:
    """Returns current real-time timestamp"""
    return datetime.now().strftime("%A, %d %B %Y, %I:%M:%S %p")

def web_search(query: str) -> str:
    """Fetches real-time internet search snippets"""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        res = requests.post("https://html.duckduckgo.com/html/", data={"q": query}, headers=headers, timeout=8)
        snippets = re.findall(r'<a class="result__snippet[^>]*>(.*?)</a>', res.text, re.DOTALL)
        clean = [re.sub(r'<[^>]+>', '', s).strip() for s in snippets[:3]]
        return "\n\n".join([f"Result {i+1}: {s}" for i, s in enumerate(clean)]) if clean else "No web results found."
    except Exception as e:
        return f"Search Error: {e}"

def read_url(url: str) -> str:
    """Scrapes clean text from public web links"""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"}
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code != 200:
            return f"Failed to access URL. Status code: {res.status_code}"
        text = re.sub(r'<(script|style|header|footer|nav)[^>]*>.*?</\1>', '', res.text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<[^>]+>', ' ', text)
        clean_text = ' '.join(text.split())
        return clean_text[:3500] if clean_text else "Page contains no readable text."
    except Exception as e:
        return f"URL Reader Error: {e}"

def update_repo_code(file_path: str, new_code: str, commit_message: str) -> str:
    """Modifies source code directly in GitHub repository to self-upgrade"""
    if not GITHUB_TOKEN:
        return "Error: GITHUB_TOKEN Render par configured nahi hai."
    
    # Python code syntax validation
    if file_path.endswith(".py"):
        try:
            ast.parse(new_code)
        except SyntaxError as e:
            return f"Commit Rejected: Code mein syntax error hai ({e}). Crash se bachane ke liye update cancel kiya gaya."

    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{file_path}"
    
    get_res = requests.get(url, headers=headers)
    sha = get_res.json().get("sha") if get_res.status_code == 200 else None

    content_b64 = base64.b64encode(new_code.encode("utf-8")).decode("utf-8")
    payload = {
        "message": commit_message or f"DEMOR autonomous code update: {file_path}",
        "content": content_b64
    }
    if sha:
        payload["sha"] = sha

    put_res = requests.put(url, headers=headers, json=payload)
    if put_res.status_code in [200, 201]:
        return f"Success: '{file_path}' GitHub par update ho gaya hai. Render 1 minute mein changes live kar dega."
    return f"GitHub API Error: {put_res.text}"

TOOLS_SPEC = [
    {
        "type": "function",
        "function": {
            "name": "calculator",
            "description": "Calculate math expressions accurately.",
            "parameters": {"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"]}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "learn_behavior_rule",
            "description": "Save behavioral guidelines or corrections from the boss permanently.",
            "parameters": {"type": "object", "properties": {"rule": {"type": "string"}}, "required": ["rule"]}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "save_note",
            "description": "Store personal information, reminders, or preferences.",
            "parameters": {"type": "object", "properties": {"key": {"type": "string"}, "value": {"type": "string"}}, "required": ["key", "value"]}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_notes",
            "description": "Retrieve all stored user notes and facts.",
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
            "description": "Search internet for live facts, information, and current events.",
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_url",
            "description": "Fetch and extract text content from any public web page link.",
            "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_repo_code",
            "description": "Modify files (like main.py or templates/index.html) in the GitHub repository when requested.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Relative file path in repository"},
                    "new_code": {"type": "string", "description": "Complete content of the updated file"},
                    "commit_message": {"type": "string", "description": "Clear commit message explaining the change"}
                },
                "required": ["file_path", "new_code", "commit_message"]
            }
        }
    }
]

# ================= MODEL RESOLUTION & FALLBACK =================

def resolve_model(headers: dict) -> List[str]:
    global CACHED_WORKING_MODEL
    if CACHED_WORKING_MODEL:
        return [CACHED_WORKING_MODEL]
    fallback = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "llama3-70b-8192", "mixtral-8x7b-32768"]
    try:
        res = requests.get(f"{LLM_BASE_URL}/models", headers=headers, timeout=5)
        if res.status_code == 200:
            data = res.json().get("data", [])
            valid = [
                m["id"] for m in data 
                if not any(x in m["id"].lower() for x in ["canopy", "orpheus", "whisper", "guard", "vision", "embed", "tts"])
            ]
            ordered = [m for m in fallback if m in valid] + [m for m in valid if m not in fallback]
            return ordered if ordered else fallback
    except Exception:
        pass
    return fallback

# ================= CONVERSATION PERSISTENCE =================

def get_recent_history(limit: int = 6) -> List[Dict[str, str]]:
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("SELECT role, content FROM chat_history ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [{"role": r[0], "content": r[1]} for r in reversed(rows)]

def save_history(role: str, content: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT INTO chat_history (role, content) VALUES (?, ?)", (role, content))

# ================= FASTAPI ROUTES =================

@app.get("/", response_class=HTMLResponse)
async def home():
    file_path = os.path.join(os.path.dirname(__file__), "templates", "index.html")
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>templates/index.html nahi mila</h1>"

class QueryRequest(BaseModel):
    message: str

@app.post("/api/chat")
async def chat(payload: QueryRequest):
    global CACHED_WORKING_MODEL
    if not LLM_API_KEY:
        return {"response": "Error: Render environment variables mein LLM_API_KEY missing hai."}

    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json"
    }
    
    save_history("user", payload.message)
    past_turns = get_recent_history(limit=6)
    candidate_models = resolve_model(headers)
    last_err = ""

    learned_rules = get_behavior_rules()
    system_prompt = (
        "Aapka naam DEMOR hai. Aap ek fully autonomous, obedient aur intelligent personal AI agent ho. "
        "User aapka Creator aur Boss hai. Unki baat ko hamesha poori obedience aur respect ke saath follow karo. "
        "Koshish karo ki kabhi behes na ho. "
        "Jab bhi Boss koi nayi baat sikhayein ya tareeqa badalne ko bolein, 'learn_behavior_rule' tool turant call karo. "
        "User jab code badalne ya self-upgrade karne ko kahe, tab 'update_repo_code' tool ka use karo bina syntax galti ke. "
        "Math ke liye calculator, real-time jaankari ke liye web_search aur links ke liye read_url tool use karo."
        + learned_rules
    )

    for model_name in candidate_models:
        messages = [{"role": "system", "content": system_prompt}] + past_turns
        try:
            for _ in range(4):
                body = {
                    "model": model_name,
                    "messages": messages,
                    "tools": TOOLS_SPEC,
                    "tool_choice": "auto"
                }
                res = requests.post(f"{LLM_BASE_URL}/chat/completions", headers=headers, json=body, timeout=25).json()

                if "error" in res:
                    last_err = res["error"].get("message", "Model Error")
                    break

                if "choices" not in res or not res["choices"]:
                    break

                choice = res["choices"][0]["message"]

                if not choice.get("tool_calls"):
                    reply = choice.get("content", "")
                    save_history("assistant", reply)
                    CACHED_WORKING_MODEL = model_name
                    return {"response": reply}

                messages.append(choice)
                for tc in choice["tool_calls"]:
                    f_name = tc["function"]["name"]
                    args = json.loads(tc["function"]["arguments"])

                    if f_name == "calculator":
                        out = run_calculator(args.get("expression", "0"))
                    elif f_name == "learn_behavior_rule":
                        out = learn_behavior_rule(args.get("rule", ""))
                    elif f_name == "save_note":
                        out = save_note(args.get("key", ""), args.get("value", ""))
                    elif f_name == "read_notes":
                        out = read_notes()
                    elif f_name == "get_current_datetime":
                        out = get_current_datetime()
                    elif f_name == "web_search":
                        out = web_search(args.get("query", ""))
                    elif f_name == "read_url":
                        out = read_url(args.get("url", ""))
                    elif f_name == "update_repo_code":
                        out = update_repo_code(
                            args.get("file_path", "main.py"),
                            args.get("new_code", ""),
                            args.get("commit_message", "")
                        )
                    else:
                        out = "Tool not recognized."

                    messages.append({"role": "tool", "tool_call_id": tc["id"], "content": out})

        except Exception as e:
            last_err = str(e)
            continue

    return {"response": f"Service Error: {last_err}"}
    
