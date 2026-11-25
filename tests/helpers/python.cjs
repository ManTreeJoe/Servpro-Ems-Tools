const childProcess = require('node:child_process');
const path = require('node:path');

// PYTHON is one executable path, not a shell command (spaces are supported).
function execPython(args, options = {}) {
  const executable = (process.env.PYTHON || '').trim() || 'python';
  return childProcess.execFileSync(executable, args, {
    cwd: path.resolve(__dirname, '../..'),
    ...options,
    shell: false,
  });
}

module.exports = {execPython};
