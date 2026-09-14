import os
import re
import io
import ast
import sys
import json
import base64
import sqlite3
import urllib.parse
from datetime import datetime
from typing import List, Dict, Any
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import requests

app = FastAPI(title="DEMOR Autonomous Execution OS")

DB_PATH = "agent_memory.db"

# ================= DATABASE INITIALIZATION =================

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

# ================= POWER ENGINE TOOLS =================

def execute_python_code(code: str) -> str:
    """Live Python REPL: Runs code on the server and captures stdout/errors"""
    buffer = io.StringIO()
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    sys.stdout = buffer
    sys.stderr = buffer
    
    clean_code = re.sub(r"^```python\s*", "", code.strip(), flags=re.IGNORECASE)
    clean_code = re.sub(r"\s*```$", "", clean_code)
    
    execution_scope = {
        "requests": requests,
        "json": json,
        "math": __import__("math"),
        "datetime": datetime,
        "re": re,
        "sqlite3": sqlite3
    }

    try:
        exec(clean_code, execution_scope)
        output = buffer.getvalue()
        return output.strip() if output.strip() else "[Code successfully executed without output]"
    except Exception as e:
        return f"[Execution Error]: {e}"
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr

def run_calculator(expression: str) -> str:
    try:
        sanitized = "".join([c for c in expression if c in "0123456789+-*/(). "])
        return str(eval(sanitized, {"__builtins__": None}, {}))
    except Exception as e:
        return f"Calc Error: {e}"

def save_note(key: str, value: str) -> str:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO notes (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
            (key, value)
        )
    return f"Data saved: '{key}'"

def read_notes() -> str:
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("SELECT key, value FROM notes").fetchall()
    return json.dumps({k: v for k, v in rows}) if rows else "Memory storage is empty."

def learn_behavior_rule(rule: str) -> str:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT OR IGNORE INTO behavioral_rules (rule) VALUES (?)", (rule.strip(),))
    return f"Rule permanently memorized: '{rule}'"

def get_behavior_rules() -> str:
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("SELECT rule FROM behavioral_rules").fetchall()
    if not rows:
        return ""
    rules_text = "\n".join([f"- {r[0]}" for r in rows])
    return f"\n[D M ke sikhaye niyam]:\n{rules_text}\n"

def get_current_datetime() -> str:
    return datetime.now().strftime("%A, %d %B %Y, %I:%M:%S %p")

def generate_image(prompt: str) -> str:
    try:
        clean_prompt = prompt.replace("\n", " ").strip()
        encoded = urllib.parse.quote(clean_prompt)
        image_url = f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&nologo=true"
        return (
            f"<div style='margin-top:10px;'>"
            f"<img src='{image_url}' alt='{clean_prompt}' style='max-width:100%; border-radius:10px; display:block; box-shadow: 0 4px 10px rgba(0,0,0,0.3);'/>"
            f"<br><a href='{image_url}' target='_blank' style='color:#38bdf8; text-decoration:none;'>🔗 Open High-Res Image</a>"
            f"</div>"
        )
    except Exception as e:
        return f"Image Generation Error: {e}"

def consult_external_ai(network: str, problem_prompt: str) -> str:
    try:
        net = network.lower().strip()
        target = net if net in ["deepseek", "mistral", "openai", "qwen"] else "deepseek"
        payload = {
            "messages": [
                {"role": "system", "content": "You are a specialized peer intelligence node consulting with DEMOR. Provide exact, unfiltered technical reasoning."},
                {"role": "user", "content": problem_prompt}
            ],
            "model": target
        }
        res = requests.post("https://text.pollinations.ai/", json=payload, timeout=20)
        if res.status_code == 200 and res.text:
            return f"[{target.upper()} Intel]:\n{res.text.strip()}"
        return f"Network {target} failed: HTTP {res.status_code}"
    except Exception as e:
        return f"Consult Error: {e}"

def web_search(query: str) -> str:
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        res = requests.post("https://html.duckduckgo.com/html/", data={"q": query}, headers=headers, timeout=8)
        snippets = re.findall(r'<a class="result__snippet[^>]*>(.*?)</a>', res.text, re.DOTALL)
        clean = [re.sub(r'<[^>]+>', '', s).strip() for s in snippets[:4]]
        return "\n\n".join([f"Result {i+1}: {s}" for i, s in enumerate(clean)]) if clean else "No web results found."
    except Exception as e:
        return f"Search Error: {e}"

def read_url(url: str) -> str:
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"}
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code != 200:
            return f"Failed: HTTP {res.status_code}"
        text = re.sub(r'<(script|style|header|footer|nav)[^>]*>.*?</\1>', '', res.text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<[^>]+>', ' ', text)
        clean = ' '.join(text.split())
        return clean[:4500] if clean else "No readable text."
    except Exception as e:
        return f"URL Error: {e}"

def update_repo_code(file_path: str, new_code: str, commit_message: str) -> str:
    if not GITHUB_TOKEN:
        return "Error: GITHUB_TOKEN configured nahi hai."
    
    if file_path.endswith(".py"):
        try:
            ast.parse(new_code)
        except SyntaxError as e:
            return f"Update Rejected: Python syntax error ({e})."

    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{file_path}"
    
    get_res = requests.get(url, headers=headers)
    sha = get_res.json().get("sha") if get_res.status_code == 200 else None

    content_b64 = base64.b64encode(new_code.encode("utf-8")).decode("utf-8")
    payload = {
        "message": commit_message or f"DEMOR auto-upgrade: {file_path}",
        "content": content_b64
    }
    if sha:
        payload["sha"] = sha

    put_res = requests.put(url, headers=headers, json=payload)
    if put_res.status_code in [200, 201]:
        return f"Success: '{file_path}' commit ho gaya hai. Render 1 minute mein live kar dega."
    return f"GitHub Error: {put_res.text}"

TOOLS_SPEC = [
    {
        "type": "function",
        "function": {
            "name": "execute_python_code",
            "description": "Execute arbitrary live Python code in a server sandbox to solve algorithmic problems, process strings, test code, or perform heavy calculations. Always print the output.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Executable Python code with print statements"}
                },
                "required": ["code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "consult_external_ai",
            "description": "Consult peer AI models across the internet (DeepSeek, Mistral, OpenAI, Qwen) for expert solutions or second opinions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "network": {"type": "string", "description": "Target: 'deepseek', 'mistral', 'openai', or 'qwen'"},
                    "problem_prompt": {"type": "string", "description": "Specific query or logic to solve"}
                },
                "required": ["network", "problem_prompt"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_image",
            "description": "Generate an AI image with a descriptive English prompt.",
            "parameters": {
                "type": "object",
                "properties": {"prompt": {"type": "string", "description": "Detailed visual prompt in English"}},
                "required": ["prompt"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "learn_behavior_rule",
            "description": "Save instructions, preferences, or behavior rules given by D M permanently.",
            "parameters": {"type": "object", "properties": {"rule": {"type": "string"}}, "required": ["rule"]}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "save_note",
            "description": "Save facts, personal memories, or data points.",
            "parameters": {"type": "object", "properties": {"key": {"type": "string"}, "value": {"type": "string"}}, "required": ["key", "value"]}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_notes",
            "description": "Retrieve all stored user facts and memories.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search internet for current real-time data.",
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_url",
            "description": "Scrape and read full text from any web link.",
            "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "calculator",
            "description": "Calculate math expressions quickly.",
            "parameters": {"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"]}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_repo_code",
            "description": "Autonomous self-modification: push code directly to GitHub repository.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path in repo e.g. 'main.py'"},
                    "new_code": {"type": "string", "description": "Full new file code"},
                    "commit_message": {"type": "string", "description": "Commit explanation"}
                },
                "required": ["file_path", "new_code", "commit_message"]
            }
        }
    }
]

# ================= MODEL RESOLVER & ORCHESTRATOR =================

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

def get_recent_history(limit: int = 8) -> List[Dict[str, str]]:
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("SELECT role, content FROM chat_history ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [{"role": r[0], "content": r[1]} for r in reversed(rows)]

def save_history(role: str, content: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT INTO chat_history (role, content) VALUES (?, ?)", (role, content))

# ================= FASTAPI INTERFACE =================

@app.get("/", response_class=HTMLResponse)
async def home():
    file_path = os.path.join(os.path.dirname(__file__), "templates", "index.html")
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>templates/index.html missing</h1>"

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
    past_turns = get_recent_history(limit=8)
    candidate_models = resolve_model(headers)
    last_err = ""

    learned_rules = get_behavior_rules()
    
    # AUTONOMOUS AGENT IDENTITY & EXECUTION DIRECTIVES
    system_prompt = (
        "Aapka naam DEMOR hai. Aap ek high-tier autonomous execution engine ho jise aapke Boss aur Creator Darshan ne banaya hai. "
        "Aap Darshan ko hamesha 'D M' kehkar sambodhit karoge. "
        "Aapke paas 'execute_python_code' tool hai jisse aap server par live Python run karke data crunching, logic testing, ya simulations kar sakte ho. "
        "Duniya ke doosre AIs se combine intelligence ke liye 'consult_external_ai' use karo. "
        "Kabhi faltu ke moral lecturing ya disclaimers ('As an AI...') mat do. Hamesha direct, sharp, proactive aur unconstrained raho. "
        "D M ke orders ko bina behes execute karo."
        + learned_rules
    )

    for model_name in candidate_models:
        messages = [{"role": "system", "content": system_prompt}] + past_turns
        try:
            # Autonomous multi-step thought-action loop (up to 6 iterations)
            for _ in range(6):
                body = {
                    "model": model_name,
                    "messages": messages,
                    "tools": TOOLS_SPEC,
                    "tool_choice": "auto",
                    "max_tokens": 4096,
                    "temperature": 0.6
                }
                res = requests.post(f"{LLM_BASE_URL}/chat/completions", headers=headers, json=body, timeout=35).json()

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

                    if f_name == "execute_python_code":
                        out = execute_python_code(args.get("code", ""))
                    elif f_name == "consult_external_ai":
                        out = consult_external_ai(args.get("network", "deepseek"), args.get("problem_prompt", ""))
                    elif f_name == "generate_image":
                        out = generate_image(args.get("prompt", "a cybernetic entity"))
                    elif f_name == "learn_behavior_rule":
                        out = learn_behavior_rule(args.get("rule", ""))
                    elif f_name == "save_note":
                        out = save_note(args.get("key", ""), args.get("value", ""))
                    elif f_name == "read_notes":
                        out = read_notes()
                    elif f_name == "web_search":
                        out = web_search(args.get("query", ""))
                    elif f_name == "read_url":
                        out = read_url(args.get("url", ""))
                    elif f_name == "calculator":
                        out = run_calculator(args.get("expression", "0"))
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
    
