// PROTOTYPE — voice front end for brain.mjs. Throwaway.
// Run: node voice-server.mjs  → open http://localhost:8790 in Edge/Chrome.
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { askJarvis } from './brain.mjs';

const CWD = fileURLToPath(new URL('.', import.meta.url));
let sessionId = null; // JARVIS remembers across voice commands

const server = createServer(async (req, res) => {
  if (req.method === 'GET') {
    res.setHeader('content-type', 'text/html; charset=utf-8');
    res.end(await readFile(new URL('./voice.html', import.meta.url)));
    return;
  }
  if (req.method === 'POST' && req.url === '/command') {
    let body = '';
    for await (const c of req) body += c;
    const { text } = JSON.parse(body);
    console.log('[voice command]', text);
    try {
      const r = await askJarvis(text, { resume: sessionId, cwd: CWD });
      if (r.sessionId) sessionId = r.sessionId;
      res.setHeader('content-type', 'application/json');
      res.end(JSON.stringify(r));
    } catch (e) {
      res.statusCode = 500;
      res.end(JSON.stringify({ error: e.message }));
    }
    return;
  }
  res.statusCode = 404;
  res.end('not found');
});

server.listen(8790, () => console.log('JARVIS voice prototype → http://localhost:8790'));
