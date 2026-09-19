"""One isolated live JSON qualification request through the engine interface.

The caller supplies only an explicit OpenRouter key and model in the environment.
Artifacts contain public inputs and sanitized observations, never credentials.
"""
import asyncio
import datetime
import json
import os
import re
from pathlib import Path

from evaluations._live_config import configure_live_environment

MODEL = configure_live_environment()
from co_scientist.llm import CompletionSpec, LLMCallOptions, call_llm_json
from co_scientist.llm_free_catalog import current_catalog, verify_model
from co_scientist.llm_free_policy import enforce_free_request
from evaluations._usage_evidence import capture_usage

SCHEMA = {
    'type': 'object',
    'properties': {
        'label': {'type': 'string', 'enum': ['supports', 'contradicts', 'insufficient']},
        'quote': {'type': 'string'},
    },
    'required': ['label', 'quote'],
    'additionalProperties': False,
}
PROMPT = '''Classify whether the passage supports the claim. Return only JSON
with label and a verbatim quote. Claim: Treatment X reduced cell viability in
this experiment. Passage: In this experiment, treatment X reduced cell viability
by 30% relative to vehicle. This observation does not establish clinical benefit.'''

async def main():
    verify_model(MODEL.removeprefix('openrouter/'), current_catalog())
    admission = {'model': MODEL, 'messages': [{'role': 'user', 'content': PROMPT}]}
    await enforce_free_request(admission)
    report = {
        'observed_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'requested_model': MODEL, 'prompt': PROMPT, 'schema': SCHEMA,
        'admission_body': admission['extra_body'], 'max_attempts': 1,
        'requested_thinking': False,
    }
    with capture_usage('qualification_json', live=True) as evidence:
        try:
            result = await asyncio.wait_for(call_llm_json(
                PROMPT, CompletionSpec(model_name=MODEL, max_tokens=2048,
                    temperature=0, json_schema=SCHEMA), max_attempts=1,
                options=LLMCallOptions(use_cache=False, enable_thinking=False),
            ), timeout=90)
            report['response'] = result
            report['passed'] = (result.get('label') == 'supports'
                and bool(result.get('quote')) and result['quote'] in PROMPT)
        except Exception as exc:
            report['passed'] = False
            report['error_type'] = type(exc).__name__
            report['error'] = re.sub(r'user_[A-Za-z0-9]+', '[redacted-account]',
                str(exc).replace(os.environ['OPENROUTER_API_KEY'], '[redacted]'))[:2000]
    report.update(evidence)
    output = Path(os.environ['QUALIFICATION_OUTPUT'])
    output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'model': MODEL, 'passed': report['passed'],
        'error_type': report.get('error_type'), 'artifact': str(output)}))

if __name__ == '__main__':
    asyncio.run(main())
