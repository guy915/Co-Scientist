import {createServer} from 'node:http';
import {readFile, stat} from 'node:fs/promises';
import {resolve, extname, sep} from 'node:path';
import {gzipSync} from 'node:zlib';

const root = resolve(process.argv[2] || 'dist');
const port = Number(process.env.FP_PORT || 4173);
const api = process.env.FP_API || 'http://127.0.0.1:8108';
if (!['localhost', '127.0.0.1'].includes(new URL(api).hostname)) {
  throw new Error('Performance preview requires a loopback API');
}
const rules = [];
let rule;
for (const line of (await readFile(resolve(root, '_headers'), 'utf8')).split(
  '\n',
)) {
  if (!line.trim() || line.trim().startsWith('#')) continue;
  if (!/^\s/.test(line)) {
    rule = {pattern: line.trim(), headers: {}};
    rules.push(rule);
  } else {
    const colon = line.indexOf(':');
    if (!rule || colon < 0) throw new Error('Invalid _headers');
    rule.headers[line.slice(0, colon).trim().toLowerCase()] = line
      .slice(colon + 1)
      .trim();
  }
}
const types = {
  '.html': 'text/html',
  '.js': 'text/javascript',
  '.css': 'text/css',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.webp': 'image/webp',
  '.woff2': 'font/woff2',
  '.json': 'application/json',
};
const server = createServer(async (req, res) => {
  try {
    const url = new URL(req.url, `http://127.0.0.1:${port}`);
    if (/^\/(api(?:\/|$)|status$|health$)/.test(url.pathname)) {
      const upstream = await fetch(new URL(url.pathname + url.search, api), {
        headers: {
          'X-Client-ID': req.headers['x-client-id'] || 'fp-performance',
        },
      });
      res.writeHead(upstream.status, {
        'content-type':
          upstream.headers.get('content-type') || 'application/json',
      });
      res.end(Buffer.from(await upstream.arrayBuffer()));
      return;
    }
    let assetPath = url.pathname;
    let file = resolve(root, '.' + decodeURIComponent(url.pathname));
    if (file !== root && !file.startsWith(root + sep)) {
      res.writeHead(403).end();
      return;
    }
    if (file === root) file = resolve(root, 'index.html');
    try {
      if (!(await stat(file)).isFile()) throw new Error('not a file');
    } catch {
      if (url.pathname.startsWith('/assets/')) {
        res.writeHead(404).end();
        return;
      }
      file = resolve(root, 'index.html');
      assetPath = '/index.html';
    }
    const headers = {
      'content-type': types[extname(file)] || 'application/octet-stream',
      vary: 'Accept-Encoding',
    };
    for (const {pattern, headers: values} of rules) {
      const regex = new RegExp(
        '^' +
          pattern
            .split('*')
            .map(part => part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
            .join('.*') +
          '$',
      );
      if (regex.test(assetPath)) Object.assign(headers, values);
    }
    let body = await readFile(file);
    if (
      /\b gzip\b|\bgzip\b/.test(req.headers['accept-encoding'] || '') &&
      /\.(html|js|css|svg|json)$/.test(file)
    ) {
      body = gzipSync(body, {level: 9});
      headers['content-encoding'] = 'gzip';
    }
    headers['content-length'] = body.length;
    res.writeHead(200, headers);
    res.end(req.method === 'HEAD' ? undefined : body);
  } catch (error) {
    console.error(error.message);
    res.writeHead(500).end();
  }
});
server.listen(port, '127.0.0.1', () =>
  console.log(`Static performance preview: http://127.0.0.1:${port}`),
);
