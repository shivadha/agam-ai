from src.engine.orchestrator import WorkflowEngine

payload = {
    'nodes': [
        {'id':'n1',  'type':'article-trigger',  'data':{}},
        {'id':'n2',  'type':'gen-script',        'data':{}},
        {'id':'n3',  'type':'gen-title',         'data':{}},
        {'id':'n4',  'type':'gen-desc',          'data':{}},
        {'id':'n5',  'type':'gen-tags',          'data':{}},
        {'id':'n6',  'type':'gen-seo',           'data':{}},
        {'id':'n7',  'type':'tts',               'data':{}},
        {'id':'n8','type':'gen-image',         'data':{}},
        {'id':'n8_5','type':'img-to-video',       'data':{}},
        {'id':'n9',  'type':'assemble-video',    'data':{}}
    ],
    'edges': [
        {'source':'n1','target':'n2'},
        {'source':'n2','target':'n3'},
        {'source':'n2','target':'n4'},
        {'source':'n2','target':'n5'},
        {'source':'n3','target':'n6'},
        {'source':'n4','target':'n6'},
        {'source':'n5','target':'n6'},
        {'source':'n6','target':'n7'},
        {'source':'n6','target':'n8'},
        {'source':'n8','target':'n8_5'},
        {'source':'n7','target':'n9'},
        {'source':'n8_5','target':'n9'}
    ]
}

engine = WorkflowEngine(payload)
results = engine.run()

print("\n=== WORKFLOW RESULTS ===")
for node_id, res in results.items():
    status = res.get('status', 'unknown')
    node_type = res.get('node_type', '?')
    err = res.get('error', '')
    msg = f"{node_id} ({node_type}): {status}"
    if err:
        msg += f" -- ERROR: {err}"
    print(msg)
