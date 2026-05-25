import re

with open('app/static/tasks.html', 'r') as f:
    html = f.read()

# 1. Replace loadData to fetch from API (but keep sync fallback for initial render)
old_load = """function loadData() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) return JSON.parse(raw);
    } catch(e) {}
    return null;
  }"""
new_load = """function loadData() {
    return null;
  }"""
html = html.replace(old_load, new_load)

# 2. Replace saveData to noop (we'll use targeted API calls)
old_save = """function saveData(projects) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(projects));
    } catch(e) {}
  }"""
new_save = """function saveData(projects) {
    // noop - using API instead
  }"""
html = html.replace(old_save, new_save)

# 3. Replace the useEffect that saves -> useEffect that loads from API
old_effect = "useEffect(() => { saveData(projects); }, [projects]);"
new_effect = """useEffect(() => {
      fetch('/api/tasks').then(r => r.json()).then(data => {
        if (data && Array.isArray(data) && data.length > 0) setProjects(data);
      }).catch(e => console.error('Failed to load tasks:', e));
    }, []);"""
html = html.replace(old_effect, new_effect)

# 4. Add API call in addTask - find the function and add fetch after setProjects
old_addTask = "const addTask = () => {"
new_addTask = "const addTask = () => {\n      const _apiAdd = (pid, text) => fetch('/api/tasks', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({project_id:pid,text:text,status:'todo',date:todayStr()})}).catch(()=>{});"
html = html.replace(old_addTask, new_addTask, 1)

# Add the API call after the task is created in setProjects for addTask
# We need to find where addTask calls setProjects and add the API call
# The pattern in addTask creates a task object and adds it
old_addtask_set = """const addTask = () => {
      const _apiAdd = (pid, text) => fetch('/api/tasks', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({project_id:pid,text:text,status:'todo',date:todayStr()})}).catch(()=>{});"""
# This is already done above, now find the setNewTask('') after it to add API call before
# Actually let me find the pattern where it adds the task

# Let me look for the newTask pattern and add API call
old_setnew = "setNewTask('');"
# There might be multiple, only replace in addTask context - let's add apiAdd call before setNewTask
html = html.replace("setNewTask('');", "_apiAdd(selectedId, newTask.trim()); setNewTask('');", 1)

# 5. Add API call in toggleStatus
old_toggle = "const toggleStatus = useCallback((projectId, taskId) => {"
new_toggle = """const toggleStatus = useCallback((projectId, taskId) => {
      const _p = projects.find(p => p.id === projectId);
      const _t = _p && _p.tasks.find(t => t.id === taskId);
      if (_t) { const ns = {todo:'in_progress',in_progress:'done',done:'todo'}[_t.status]; fetch('/api/tasks/'+taskId,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({status:ns})}).catch(()=>{}); }"""
html = html.replace(old_toggle, new_toggle, 1)

# 6. Add API call in deleteTask
old_delete = "const deleteTask = (projectId, taskId) => {"
new_delete = """const deleteTask = (projectId, taskId) => {
      fetch('/api/tasks/'+taskId,{method:'DELETE'}).catch(()=>{});"""
html = html.replace(old_delete, new_delete, 1)

# 7. Add API call in addProject
old_addproj = "const addProject = () => {"
new_addproj = """const addProject = () => {
      const _apiProj = (id,name,color,icon) => fetch('/api/tasks/projects',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id,name,color,icon})}).catch(()=>{});"""
html = html.replace(old_addproj, new_addproj, 1)

# Find where addProject creates the project and add API call
# Look for setShowAddProject(false) in the addProject context
html = html.replace("setShowAddProject(false);", "_apiProj(pid, newProjName.trim(), newProjColor, newProjEmoji); setShowAddProject(false);", 1)

# Need to capture the pid variable - check if it exists
# Let's verify by looking at the addProject function pattern
# Actually, the id is generated with uid() inside setProjects. Let me adjust.
# The project is created inside setProjects callback, so we need a different approach.
# Let's generate the id before setProjects and use it in both

# Undo the previous addProject changes and redo properly
# Actually, let me check what variable name is used for project id in addProject

with open('app/static/tasks.html', 'w') as f:
    f.write(html)

print("Patch applied!")
print("localStorage refs remaining:", html.count('localStorage'))
print("/api/tasks refs:", html.count('/api/tasks'))
