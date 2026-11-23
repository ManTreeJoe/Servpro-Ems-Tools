const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const cp = require('node:child_process');
const {execPython} = require('./helpers/python.cjs');
const originalExec = cp.execFileSync;
const originalPython = process.env.PYTHON;
const calls = [];
try {
  cp.execFileSync = (...args) => { calls.push(args); return 'fixture'; };
  delete process.env.PYTHON;
  assert.equal(execPython(['-c', 'pass'], {encoding:'utf8'}), 'fixture');
  assert.equal(calls[0][0], 'python');
  assert.deepEqual(calls[0][1], ['-c', 'pass']);
  assert.equal(calls[0][2].cwd, path.resolve(__dirname, '..'));
  assert.equal(calls[0][2].encoding, 'utf8');
  assert.equal(calls[0][2].shell, false);
  process.env.PYTHON = 'C:/Fictional Tools/Python/python.exe';
  execPython(['--version'], {shell:true});
  assert.equal(calls[1][0], process.env.PYTHON);
  assert.equal(calls[1][2].shell, false, 'never turn an executable path into a shell command');
  process.env.PYTHON = '   ';
  execPython(['--version']);
  assert.equal(calls[2][0], 'python');
  cp.execFileSync = () => { throw Object.assign(new Error('missing interpreter'), {code:'ENOENT'}); };
  assert.throws(() => execPython(['--version']), {code:'ENOENT'});
} finally {
  cp.execFileSync = originalExec;
  if (originalPython === undefined) delete process.env.PYTHON;
  else process.env.PYTHON = originalPython;
}
for (const name of ['comment_reactions.cjs', 'daily_run_completion.cjs', 'job_forms.cjs']) {
  const source = fs.readFileSync(path.join(__dirname, name), 'utf8');
  assert(source.includes("require('./helpers/python.cjs')"), name);
  assert(!/[A-Z]:[\\/].*python\.exe/i.test(source), name + ' has a machine-specific interpreter');
}
const skips = JSON.parse(fs.readFileSync(path.join(__dirname, '../.github/ci-skips.json'), 'utf8'));
assert(!('comment_reactions.cjs' in skips.node_scripts));
assert(!('daily_run_completion.cjs' in skips.node_scripts));
console.log('PASS Python test launcher: PATH, override with spaces, root cwd, no shell, errors propagated; callers enabled');
