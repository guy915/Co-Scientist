import asyncio
import datetime
import json
import pathlib
import time
from types import SimpleNamespace

from co_scientist.mcp_client import MCPToolClient

OUT = pathlib.Path('/tmp/coscientist-campaign-retrieval/results.json')
async def main():
    client = MCPToolClient(server_url='http://127.0.0.1:8898/mcp')
    await client.initialize()
    _, schemas = client.get_tools()
    report = {'kind': 'live MCP retrieval; no model inference', 'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'revision': '3bd22758', 'isolation': {'ambient_credentials': False, 'dotenv': False, 'campaign_mode': True}, 'advertised_tools': [s['function']['name'] for s in schemas], 'calls': []}
    cases = [
        ('check_pubmed_available', {}, False),
        ('search_europepmc', {'query': 'EXT_ID:22745249 AND SRC:MED', 'max_results': 1}, True),
        ('search_pubmed', {'query': '22745249[uid]', 'max_papers': 1}, False),
        ('search_openalex', {'query': 'A programmable dual-RNA-guided DNA endonuclease in adaptive bacterial immunity', 'max_papers': 1}, False),
    ]
    for name, args, model_shape in cases:
        started = time.monotonic()
        entry = {'tool': name, 'arguments': args, 'interface': 'execute_tool_call' if model_shape else 'call_tool'}
        try:
            if model_shape:
                raw = (await client.execute_tool_call(SimpleNamespace(id='campaign-public-evidence', function=SimpleNamespace(name=name, arguments=json.dumps(args)))))['content']
            else:
                raw = await client.call_tool(name, **args)
            entry['result'] = json.loads(raw) if isinstance(raw, str) else raw
        except Exception as exc:
            entry['error'] = {'type': type(exc).__name__, 'message': str(exc)}
        entry['duration_seconds'] = round(time.monotonic()-started, 3)
        report['calls'].append(entry)
        OUT.write_text(json.dumps(report, indent=2))
        print(name, 'transport_error' if 'error' in entry else 'returned', flush=True)
asyncio.run(main())
