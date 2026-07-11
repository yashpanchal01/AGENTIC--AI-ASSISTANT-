// PROTOTYPE — throwaway. Answers: can headless `claude -p` be JARVIS's brain
// with zero permission prompts, and how fast? Pure module: no terminal code.
import { spawn } from 'node:child_process';

// The "tiered autonomy" safe tier, expressed as pre-approved tools.
// Destructive/outward actions are simply not in the list, so they get denied
// (never prompted) — which is exactly what we want to observe.
export const SAFE_TOOLS = ['Bash', 'Read', 'Glob', 'Grep', 'Write', 'Edit', 'WebSearch', 'WebFetch'];

const JARVIS_SYSTEM = [
  'You are JARVIS, a voice-driven Windows assistant.',
  'Act immediately on the command with reasonable assumptions; never ask clarifying questions unless the action is destructive or irreversible.',
  'Launching apps, opening browser tabs/terminals, and file operations in the user\'s folders are pre-approved.',
  'If a shell command is blocked by the sandbox, retry it with the sandbox disabled.',
  'Reply in one short spoken-style sentence when done.',
].join(' ');

export function askJarvis(command, opts = {}) {
  const {
    model = 'sonnet',
    allowedTools = SAFE_TOOLS,
    cwd = process.cwd(),
    resume = null, // session id from a previous run → JARVIS remembers context
    onEvent, // (event, msSinceSpawn) => void
  } = opts;

  const args = [
    '-p', command,
    '--output-format', 'stream-json', '--verbose',
    '--allowedTools', allowedTools.join(','),
    // Spike only: full autonomy to test the "no clicking" experience.
    // V1 re-introduces the tiered policy via allowedTools/deny rules.
    '--permission-mode', 'bypassPermissions',
    '--append-system-prompt', JARVIS_SYSTEM,
  ];
  if (resume) args.push('--resume', resume);
  if (model && model !== 'default') args.push('--model', model);

  const t0 = Date.now();
  const timings = { toInit: null, toFirstAssistant: null, toFirstTool: null, total: null };
  const toolCalls = [];
  let resultText = '';
  let denied = false;
  let sessionId = null;

  return new Promise((resolve, reject) => {
    const child = spawn('claude', args, { cwd, stdio: ['ignore', 'pipe', 'pipe'] });
    let buf = '';
    let stderr = '';
    child.stderr.on('data', (d) => { stderr += d; });
    child.stdout.on('data', (chunk) => {
      buf += chunk;
      let nl;
      while ((nl = buf.indexOf('\n')) >= 0) {
        const line = buf.slice(0, nl).trim();
        buf = buf.slice(nl + 1);
        if (!line) continue;
        let ev;
        try { ev = JSON.parse(line); } catch { continue; }
        const dt = Date.now() - t0;
        if (ev.type === 'system' && timings.toInit == null) timings.toInit = dt;
        if (ev.session_id) sessionId = ev.session_id;
        if (ev.type === 'assistant') {
          if (timings.toFirstAssistant == null) timings.toFirstAssistant = dt;
          for (const block of ev.message?.content ?? []) {
            if (block.type === 'tool_use') {
              if (timings.toFirstTool == null) timings.toFirstTool = dt;
              toolCalls.push({ name: block.name, at: dt });
            }
          }
        }
        if (ev.type === 'user') {
          const blocks = ev.message?.content;
          if (Array.isArray(blocks)) {
            for (const b of blocks) {
              const text = typeof b.content === 'string' ? b.content : JSON.stringify(b.content ?? '');
              if (b.type === 'tool_result' && /permission|denied|requires approval/i.test(text)) denied = true;
            }
          }
        }
        if (ev.type === 'result') {
          timings.total = dt;
          resultText = ev.result ?? ev.error ?? '';
          if (ev.subtype && ev.subtype !== 'success' && /permission/i.test(JSON.stringify(ev))) denied = true;
        }
        onEvent?.(ev, dt);
      }
    });
    child.on('error', reject);
    child.on('close', (code) => {
      if (timings.total == null) timings.total = Date.now() - t0;
      resolve({ ok: code === 0, code, timings, toolCalls, resultText, denied, sessionId, stderr: stderr.trim() });
    });
  });
}
