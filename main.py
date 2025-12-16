from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path
import sqlite3
from datetime import datetime

app = FastAPI(title="PMI Project Tracker (Lite)")

BASE = Path(__file__).parent
DB_PATH = BASE / "app.db"
UPLOAD_DIR = BASE / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")
templates = Jinja2Templates(directory=str(BASE / "templates"))

STATUSES = ["Not Started", "Researching", "In Progress", "Development Phase", "Completed"]
PRIORITIES = ["Low", "Moderate", "High"]

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db()
    cur = conn.cursor()
    cur.execute("""
      CREATE TABLE IF NOT EXISTS projects(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        description TEXT,
        due_date TEXT,
        priority TEXT NOT NULL,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
      )
    """)
    cur.execute("""
      CREATE TABLE IF NOT EXISTS updates(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        message TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(project_id) REFERENCES projects(id)
      )
    """)
    cur.execute("""
      CREATE TABLE IF NOT EXISTS attachments(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        filename TEXT NOT NULL,
        url TEXT NOT NULL,
        uploaded_at TEXT NOT NULL,
        FOREIGN KEY(project_id) REFERENCES projects(id)
      )
    """)
    conn.commit()
    conn.close()

init_db()

def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    conn = db()
    rows = conn.execute("""
      SELECT * FROM projects
      ORDER BY
        CASE WHEN status='Completed' THEN 1 ELSE 0 END,
        CASE priority WHEN 'High' THEN 0 WHEN 'Moderate' THEN 1 ELSE 2 END,
        COALESCE(due_date,'9999-12-31') ASC,
        updated_at DESC
    """).fetchall()
    conn.close()
    return templates.TemplateResponse("index.html", {
        "request": request,
        "projects": rows,
        "statuses": STATUSES,
        "priorities": PRIORITIES
    })

@app.post("/projects")
def create_project(
    name: str = Form(...),
    description: str = Form(""),
    due_date: str = Form(""),
    priority: str = Form("Moderate"),
    status: str = Form("Not Started"),
):
    conn = db()
    t = now()
    conn.execute("""
      INSERT INTO projects(name, description, due_date, priority, status, created_at, updated_at)
      VALUES(?,?,?,?,?,?,?)
    """, (name, description, due_date or None, priority, status, t, t))
    conn.commit()
    conn.close()
    return RedirectResponse("/", status_code=303)

@app.get("/project/{project_id}", response_class=HTMLResponse)
def project_detail(project_id: int, request: Request):
    conn = db()
    p = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    ups = conn.execute("SELECT * FROM updates WHERE project_id=? ORDER BY created_at DESC", (project_id,)).fetchall()
    atts = conn.execute("SELECT * FROM attachments WHERE project_id=? ORDER BY uploaded_at DESC", (project_id,)).fetchall()
    conn.close()
    if not p:
        return HTMLResponse("Not found", status_code=404)
    return templates.TemplateResponse("project.html", {
        "request": request,
        "p": p,
        "updates": ups,
        "attachments": atts,
        "statuses": STATUSES,
        "priorities": PRIORITIES
    })

@app.post("/project/{project_id}/edit")
def edit_project(
    project_id: int,
    description: str = Form(""),
    due_date: str = Form(""),
    priority: str = Form("Moderate"),
    status: str = Form("Not Started"),
):
    conn = db()
    conn.execute("""
      UPDATE projects
      SET description=?, due_date=?, priority=?, status=?, updated_at=?
      WHERE id=?
    """, (description, due_date or None, priority, status, now(), project_id))
    conn.commit()
    conn.close()
    return RedirectResponse(f"/project/{project_id}", status_code=303)

@app.post("/project/{project_id}/update")
def add_update(project_id: int, message: str = Form(...)):
    conn = db()
    conn.execute("INSERT INTO updates(project_id, message, created_at) VALUES(?,?,?)",
                 (project_id, message, now()))
    conn.execute("UPDATE projects SET updated_at=? WHERE id=?", (now(), project_id))
    conn.commit()
    conn.close()
    return RedirectResponse(f"/project/{project_id}", status_code=303)

@app.post("/project/{project_id}/attach")
async def add_attachment(
    project_id: int,
    link_url: str = Form(""),
    file: UploadFile | None = File(None),
):
    conn = db()
    url = ""
    filename = ""

    if link_url.strip():
        url = link_url.strip()
        filename = link_url.strip()
    elif file is not None:
        safe_name = f"{project_id}_{int(datetime.now().timestamp())}_{file.filename}"
        dest = UPLOAD_DIR / safe_name
        content = await file.read()
        dest.write_bytes(content)
        url = f"/uploads/{safe_name}"
        filename = file.filename
    else:
        conn.close()
        return RedirectResponse(f"/project/{project_id}", status_code=303)

    conn.execute("INSERT INTO attachments(project_id, filename, url, uploaded_at) VALUES(?,?,?,?)",
                 (project_id, filename, url, now()))
    conn.execute("UPDATE projects SET updated_at=? WHERE id=?", (now(), project_id))
    conn.commit()
    conn.close()
    return RedirectResponse(f"/project/{project_id}", status_code=303)
