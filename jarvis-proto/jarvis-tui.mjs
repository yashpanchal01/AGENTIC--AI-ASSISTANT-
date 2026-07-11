// PROTOTYPE TUI — throwaway shell around brain.mjs. Delete once NOTES.md has a verdict.
import readline from 'node:readline';
import { askJarvis, SAFE_TOOLS } from './brain.mjs';

const B = (s) => `\x1b[1m${s}\x1b[0m`;
const D = (s) => `\x1b[2m${s}\x1b[0m`;
const sec = (ms) => (ms == null ? '—' : (ms / 1000).toFixed(1) + 's');

const MODELS = ['haiku', 'sonnet', 'default'];
const state = { model: 'sonnet', runs: [], status: 'idle', live: '', sessionId: null };

// --once "command" : run one command, print JSON report, exit.
const onceIdx = process.argv.indexOf('--once');
if (onceIdx !== -1) {
  const cmd = process.argv[onceIdx + 1];
  const model = process.argv.includes('--model') ? process.argv[process.argv.indexOf('--model') + 1] : 'sonnet';
  const r = await askJarvis(cmd, { model });
  console.log(JSON.stringify({ command: cmd, model, ...r }, null, 2));
  process.exit(r.ok ? 0 : 1);
}

function render() {
  console.clear();
  console.log(B('JARVIS latency spike') + D('  — prototype, throwaway'));
  console.log(`${B('model:')} ${state.model}   ${B('allowed tools:')} ${D(SAFE_TOOLS.join(', '))}`);
  console.log(`${B('status:')} ${state.status}${state.live ? '  ' + D(state.live) : ''}`);
  console.log('');
  console.log(B('runs:'));
  if (state.runs.length === 0) console.log(D('  (none yet — type a command below)'));
  for (const r of state.runs.slice(-5)) {
    const flags = [r.denied ? '\x1b[31mDENIED-SOMETHING\x1b[0m' : 'no prompts', r.ok ? 'ok' : 'FAILED'].join(', ');
    console.log(`  ${B(r.cmd.slice(0, 48))} ${D(`[${r.model}]`)}`);
    console.log(`    first-response ${B(sec(r.timings.toFirstAssistant))}  first-action ${B(sec(r.timings.toFirstTool))}  total ${B(sec(r.timings.total))}  ${D(flags)}`);
    console.log(`    tools: ${D(r.toolCalls.map((t) => t.name).join(' → ') || 'none')}`);
    if (r.resultText) console.log(`    ${D('» ' + r.resultText.replace(/\s+/g, ' ').slice(0, 100))}`);
  }
  console.log('');
  console.log(`${B('memory:')} ${state.sessionId ? D('session ' + state.sessionId.slice(0, 8) + '… (follow-ups understood)') : D('fresh conversation')}`);
  console.log(`${B('type a command')} ${D('and press enter')}   ${B(':m')} ${D('cycle model')}   ${B(':n')} ${D('new conversation')}   ${B(':q')} ${D('quit')}`);
}

const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
render();
rl.setPrompt('You> ');
rl.prompt();

rl.on('line', async (line) => {
  const cmd = line.trim();
  if (cmd === ':q') { rl.close(); return; }
  if (cmd === ':m') {
    state.model = MODELS[(MODELS.indexOf(state.model) + 1) % MODELS.length];
    render(); rl.prompt(); return;
  }
  if (cmd === ':n') { state.sessionId = null; render(); rl.prompt(); return; }
  if (!cmd) { rl.prompt(); return; }

  state.status = `running "${cmd.slice(0, 40)}"…`;
  state.live = '';
  render();
  const t0 = Date.now();
  const tick = setInterval(() => { state.live = sec(Date.now() - t0); render(); }, 500);
  try {
    const r = await askJarvis(cmd, { model: state.model, resume: state.sessionId });
    if (r.sessionId) state.sessionId = r.sessionId;
    state.runs.push({ cmd, model: state.model, ...r });
    state.status = 'idle';
  } catch (e) {
    state.status = 'spawn error: ' + e.message;
  }
  clearInterval(tick);
  state.live = '';
  render();
  rl.prompt();
});

rl.on('close', () => { console.log('\nbye'); process.exit(0); });
