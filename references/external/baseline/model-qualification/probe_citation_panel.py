"""Paced live challenge evaluation through the existing scientific assessor."""
import asyncio
import datetime
import hashlib
import json
import os
import re
import time
from pathlib import Path

import litellm
from evaluations import citation_eval

_REQUESTS = []
_TRANSPORT = litellm.acompletion
_LAST_START = 0.0

async def observed_transport(**kwargs):
    global _LAST_START
    await asyncio.sleep(max(0, 4 - (time.monotonic() - _LAST_START)))
    _LAST_START = time.monotonic()
    record = {k: kwargs.get(k) for k in ('model','max_tokens','extra_body','response_format')}
    record['prompt_sha256'] = hashlib.sha256(json.dumps(kwargs.get('messages'),sort_keys=True).encode()).hexdigest()
    _REQUESTS.append(record)
    response = await _TRANSPORT(**kwargs)
    record['response_model'] = getattr(response,'model',None)
    record['content'] = response.choices[0].message.content
    return response

litellm.acompletion = observed_transport

if __name__ == '__main__':
    root=Path(__file__).resolve().parents[4]
    record={'source_commit':os.environ['QUALIFICATION_REVISION'],
        'probe_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'requested_model':os.environ['MODEL_NAME'],'trial':int(os.environ['QUALIFICATION_TRIAL']),
        'minimum_physical_start_spacing_seconds':4}
    try:
        record['report']=citation_eval.run(use_llm=True,
            dataset_path=root/'evaluations/datasets/citation_entailment_challenge_v1.json')
    except Exception as exc:
        record['error_type']=type(exc).__name__
        record['error']=re.sub(r'user_[A-Za-z0-9]+','[redacted-account]',
            str(exc).replace(os.environ['OPENROUTER_API_KEY'],'[redacted]'))[:2000]
    record['physical_requests']=_REQUESTS
    Path(os.environ['QUALIFICATION_OUTPUT']).write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({'model':record['requested_model'],'error_type':record.get('error_type'),
        'metrics':record.get('report',{}).get('metrics'),
        'gates':record.get('report',{}).get('production_gates')}))
