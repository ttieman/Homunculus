"""Real hosted inference only. Missing credentials never fall back to a fake model."""
import json
import os
from pathlib import Path
import time
import urllib.request
import urllib.error
from dataclasses import asdict
from homunculus import ROOT
from homunculus.physics.settings import Edit

MODEL = 'muse-spark-1.3'
FIELDS = {k: {'type': 'boolean' if k == 'obstacle' else 'number'} for k in asdict(Edit())}
TOOL = {'type':'function','function':{'name':'propose_edit',
        'description':'Propose a complete supported reach edit for review. Duration seconds; angles degrees; strength/damping multipliers. Cannot edit subintervals, add actions, infer motion or control individual frames.',
        'parameters':{'type':'object','properties':FIELDS,'required':list(FIELDS),'additionalProperties':False}}}


def configured_key():
    value=os.environ.get('MODEL_API_KEY','').strip()
    if value: return value
    path=ROOT/'.env.local'
    if path.is_file():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            if line.strip().startswith('MODEL_API_KEY='):
                return line.strip().split('=',1)[1].strip().strip('"').strip("'")
    return ''


def propose(prompt, current):
    key = configured_key()
    if not key:
        raise RuntimeError('Meta inference BLOCKED: set MODEL_API_KEY in .env.local or the server environment. No fixture response is substituted.')
    if not isinstance(prompt,str) or not 1 <= len(prompt.strip()) <= 2000:
        raise ValueError('Direction must contain 1–2000 characters')
    payload = {'model': MODEL, 'messages':[
        {'role':'system','content':'You direct a supported physical arm. Use propose_edit only for supported edits. Preserve unchanged fields. Ranges: duration 2..30, shoulder_deg 5..100, elbow_deg -100..30, strength .1..2, damping .2..3. If ambiguous or unsupported, explain without a tool call. Never claim simulation or inference that did not occur.'},
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


def propose_reference(prompt, capture, current):
    """Meta edits structured timing operations; no poses, images or forces sent."""
    from copy import deepcopy
    from homunculus.capture.spatial import prepare_spatial
    motion=prepare_spatial(capture)
    timeline=motion.timeline.edited([{'operation':'set_duration','parameters':{'seconds':current.duration}}])
    key=configured_key()
    if not key: raise RuntimeError('Meta inference BLOCKED: configure MODEL_API_KEY locally')
    if not isinstance(prompt,str) or not 1<=len(prompt.strip())<=2000: raise ValueError('Direction must contain 1–2000 characters')
    command={'type':'object','properties':{
        'operation':{'type':'string','enum':['move_keyframe','set_duration','set_interpolation']},
        'targetId':{'type':'string'},
        'parameters':{'type':'object','properties':{'time':{'type':'number'},'seconds':{'type':'number'},
            'interpolation':{'type':'string','enum':['linear','smoothstep','hold']}},'additionalProperties':False}},
        'required':['operation','parameters'],'additionalProperties':False}
    tool={'type':'function','function':{'name':'edit_timeline','description':'Propose timing edits only. No new poses or forces.',
        'parameters':{'type':'object','properties':{'commands':{'type':'array','items':command,'minItems':1,'maxItems':50}},
                      'required':['commands'],'additionalProperties':False}}}
    context={'skeleton':timeline.document['skeletonId'],'duration':current.duration,
             'keyframes':[{k:f[k] for k in ('id','time','interpolation')} for f in timeline.document['keyframes']]}
    payload={'model':MODEL,'messages':[
        {'role':'system','content':'Edit animation timing using edit_timeline only. Use existing key IDs. Duration 2..30 seconds. Do not create poses, contacts or forces. Unsupported instructions must receive no tool call. Proposals are validated and reviewed before applying.'},
        {'role':'user','content':json.dumps({'animation':context,'direction':prompt})}],'tools':[tool]}
    request=urllib.request.Request('https://api.meta.ai/v1/chat/completions',data=json.dumps(payload).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
    started=time.perf_counter()
    try:
        with urllib.request.urlopen(request,timeout=45) as response: output=json.load(response)
    except urllib.error.HTTPError as exc: raise RuntimeError(f'Meta request failed (HTTP {exc.code}); no edit applied') from None
    except (urllib.error.URLError,TimeoutError): raise RuntimeError('Meta request failed; no edit applied') from None
    try:
        calls=output['choices'][0]['message'].get('tool_calls',[])
        if len(calls)!=1 or calls[0]['function']['name']!='edit_timeline': raise ValueError('Model did not propose one supported timeline edit')
        values=json.loads(calls[0]['function']['arguments'])
        if not isinstance(values,dict) or set(values)!={'commands'}: raise ValueError('Invalid timeline proposal')
        edited=timeline.edited(values['commands']);edited.validate_motion()
        proposed=deepcopy(capture);proposed['reference_animation']=edited.document
        prepare_spatial(proposed)
    except (KeyError,TypeError,IndexError,AttributeError) as exc: raise ValueError('Malformed timeline proposal; no edit applied') from exc
    edit=asdict(current);edit['duration']=float(edited.times[-1])
    return {'edit':edit,'capture':proposed,'commands':values['commands'],'base':asdict(current),
            'provenance':{'provider':'Meta','model':MODEL,'response_id':output.get('id'),'latency_s':time.perf_counter()-started,'source':'live inference'}}
