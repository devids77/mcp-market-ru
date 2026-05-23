import json, requests

all_projects = {}
for sort in ['price_asc', 'price_desc', 'area_asc', 'area_desc']:
    r = requests.get('http://147.45.214.46:8100/projects/search', params={'limit': 50, 'sort_by': sort}, timeout=30)
    for p in r.json():
        all_projects[p['id']] = p

for style in ['Скандинавский', 'Классический', 'Барнхаус', 'A-Frame', 'Финский', 'Шале', 'Фахверк']:
    try:
        r = requests.get('http://147.45.214.46:8100/projects/search', params={'limit': 50, 'style': style}, timeout=30)
        for p in r.json():
            all_projects[p['id']] = p
    except: pass

for floors in ['1 этаж', '2 этажа', '1 этаж и мансарда']:
    try:
        r = requests.get('http://147.45.214.46:8100/projects/search', params={'limit': 50, 'floors': floors}, timeout=30)
        for p in r.json():
            all_projects[p['id']] = p
    except: pass

print(f'Total unique projects: {len(all_projects)}')
with open('/opt/mcp-market/scripts/scandieco_all.json', 'w') as f:
    json.dump(list(all_projects.values()), f, ensure_ascii=False)
print('Saved to scandieco_all.json')
