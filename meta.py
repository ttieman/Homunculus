"""Real hosted inference only. Missing credentials never fall back to a fake model."""
import json
import os
import time
import urllib.request
import urllib.error
from dataclasses import asdict
from puppet import Edit

MODEL = 'muse-spark-1.3'
FIELDS = {k: {'type': 'boolean' if k == 'obstacle' else 'number'} for k in asdict(Edit())}
TOOL = {'type':'function','function':{'name':'propose_edit',
        'description':'Propose a complete supported reach edit for review. Duration seconds; angles degrees; strength/damping multipliers. Cannot edit subintervals, add actions, infer motion or control individual frames.',
        'parameters':{'type':'object','properties':FIELDS,'required':list(FIELDS),'additionalProperties':False}}}


def propose(prompt, current):
    key = os.environ.get('MODEL_API_KEY')
    if not key:
        raise RuntimeError('Meta inference BLOCKED: set MODEL_API_KEY in the server environment. No fixture response is substituted.')
    if not isinstance(prompt,str) or not 1 <= len(prompt.strip()) <= 2000:
        raise ValueError('Direction must contain 1–2000 characters')
    payload = {'model': MODEL, 'messages':[
        {'role':'system','content':'You direct a supported physical arm. Use propose_edit only for supported edits. Preserve unchanged fields. Ranges: duration 2..10, shoulder_deg 5..100, elbow_deg -100..30, strength .1..2, damping .2..3. If ambiguous or unsupported, explain without a tool call. Never claim simulation or inference that did not occur.'},
        {'role':'user','content':json.dumps({'current':asdict(current),'direction':prompt})}],
        'tools':[TOOL]}
    request = urllib.request.Request('https://api.meta.ai/v1/chat/completions',
        data=json.dumps(payload).encode(), headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request,timeout=45) as response:
            output = json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f'Meta request failed (HTTP {exc.code}); no edit applied') from None
    except (urllib.error.URLError,TimeoutError):
        raise RuntimeError('Meta request timed out or could not connect; no edit applied') from None
    try:
        message = output['choices'][0]['message']
        calls = message.get('tool_calls',[])
        if len(calls) != 1 or calls[0]['function']['name'] != 'propose_edit':
            raise ValueError('Model did not propose exactly one supported edit; refine the direction')
        values = json.loads(calls[0]['function']['arguments'])
        if set(values) != set(FIELDS):
            raise ValueError('Model returned an incomplete edit')
        edit = Edit.parse(values)
    except (KeyError,TypeError,IndexError,json.JSONDecodeError):
        raise ValueError('Malformed model response; no edit applied') from None
    return {'edit':asdict(edit),'provenance':{'provider':'Meta','model':MODEL,'response_id':output.get('id'),
            'latency_s':time.perf_counter()-started,'source':'live inference'},'base':asdict(current)}
