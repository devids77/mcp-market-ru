# ——— Tasks API endpoints ———————————————————————————————

from pydantic import BaseModel as TaskBaseModel

class TaskCreate(TaskBaseModel):
    project_id: str
    text: str
    status: str = 'todo'
    date: str = None

class TaskUpdate(TaskBaseModel):
    status: str = None
    text: str = None
    date: str = None
    sort_order: int = None

class ProjectCreate(TaskBaseModel):
    id: str
    name: str
    color: str = '#3B82F6'
    icon: str = 'P'


@app.get("/api/tasks")
async def api_get_tasks():
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM task_projects ORDER BY sort_order")
            projects = [dict(r) for r in cur.fetchall()]
            cur.execute("SELECT * FROM task_items ORDER BY sort_order, id")
            tasks = [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()
    task_map = {}
    for t in tasks:
        pid = t['project_id']
        if pid not in task_map:
            task_map[pid] = []
        task_map[pid].append({'id': t['id'], 'text': t['text'], 'status': t['status'], 'date': t['date'], 'sort_order': t['sort_order']})
    result = []
    for p in projects:
        result.append({'id': p['id'], 'name': p['name'], 'color': p['color'], 'icon': p['icon'], 'tasks': task_map.get(p['id'], [])})
    return result


@app.post("/api/tasks")
async def api_create_task(task: TaskCreate):
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""INSERT INTO task_items (project_id, text, status, date, sort_order) VALUES (%(project_id)s, %(text)s, %(status)s, %(date)s, COALESCE((SELECT MAX(sort_order)+1 FROM task_items WHERE project_id=%(project_id)s), 0)) RETURNING *""", {"project_id": task.project_id, "text": task.text, "status": task.status, "date": task.date})
            new_task = dict(cur.fetchone())
            conn.commit()
    finally:
        conn.close()
    return new_task


@app.put("/api/tasks/{task_id}")
async def api_update_task(task_id: int, task: TaskUpdate):
    updates, params = [], {"id": task_id}
    if task.status is not None: updates.append("status=%(status)s"); params["status"]=task.status
    if task.text is not None: updates.append("text=%(text)s"); params["text"]=task.text
    if task.date is not None: updates.append("date=%(date)s"); params["date"]=task.date
    if task.sort_order is not None: updates.append("sort_order=%(sort_order)s"); params["sort_order"]=task.sort_order
    if not updates: return {"error": "No fields"}
    updates.append("updated_at=NOW()")
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(f"UPDATE task_items SET {','.join(updates)} WHERE id=%(id)s RETURNING *", params)
            updated = cur.fetchone()
            conn.commit()
            return dict(updated) if updated else {"error": "Not found"}
    finally:
        conn.close()


@app.delete("/api/tasks/{task_id}")
async def api_delete_task(task_id: int):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM task_items WHERE id=%s", (task_id,))
            conn.commit()
            if cur.rowcount==0: return {"error": "Not found"}
    finally:
        conn.close()
    return {"ok": True}


@app.post("/api/tasks/projects")
async def api_create_project(project: ProjectCreate):
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""INSERT INTO task_projects (id, name, color, icon, sort_order) VALUES (%(id)s, %(name)s, %(color)s, %(icon)s, COALESCE((SELECT MAX(sort_order)+1 FROM task_projects), 0)) ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name, color=EXCLUDED.color, icon=EXCLUDED.icon RETURNING *""", {"id": project.id, "name": project.name, "color": project.color, "icon": project.icon})
            new_project = dict(cur.fetchone())
            conn.commit()
    finally:
        conn.close()
    return new_project

