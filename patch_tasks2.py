
import re

html = open('app/static/tasks.html').read()
open('app/static/tasks_backup.html','w').write(html)

# 1. Noop loadData
html = html.replace(
    "localStorage.getItem(STORAGE_KEY)",
    "null /* was localStorage */"
)

# 2. Noop saveData  
html = html.replace(
    "localStorage.setItem(STORAGE_KEY, JSON.stringify(projects));",
    "/* API-based - noop */;"
)

# 3. useEffect: load from API instead of save
html = html.replace(
    "useEffect(() => { saveData(projects); }, [projects]);",
    "useEffect(() => { fetch('/api/tasks').then(r=>r.json()).then(data=>{ if(data&&Array.isArray(data)&&data.length>0) setProjects(data); }).catch(e=>console.error('Load:',e)); }, []);"
)

# 4. addTask: API call
html = html.replace(
    "setNewTask('');",
    "fetch('/api/tasks',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({project_id:selectedId,text:newTask.trim(),status:'todo',date:todayStr()})}).catch(()=>{}); setNewTask('');",
    1
)

# 5. toggleStatus: API call
html = html.replace(
    "const toggleStatus = useCallback((projectId, taskId) => {",
    "const toggleStatus = useCallback((projectId, taskId) => { const _p=projects.find(p=>p.id===projectId),_t=_p&&_p.tasks.find(t=>t.id===taskId); if(_t){const ns={todo:'in_progress',in_progress:'done',done:'todo'}[_t.status];fetch('/api/tasks/'+taskId,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({status:ns})}).catch(()=>{});}",
    1
)

# 6. deleteTask: API call
html = html.replace(
    "const deleteTask = (projectId, taskId) => {",
    "const deleteTask = (projectId, taskId) => { fetch('/api/tasks/'+taskId,{method:'DELETE'}).catch(()=>{});",
    1
)

# 7. addProject: API call
html = html.replace(
    "setProjects(prev => [...prev, np]);",
    "fetch('/api/tasks/projects',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:np.id,name:np.name,color:np.color,icon:np.emoji})}).catch(()=>{}); setProjects(prev => [...prev, np]);",
    1
)

open('app/static/tasks.html','w').write(html)
print('Done! localStorage:', html.count('localStorage'), '| /api/tasks:', html.count('/api/tasks'))
