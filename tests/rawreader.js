// Stands in for a TUI such as Claude Code: raw-mode stdin in a console, logs what arrives.
const fs = require('fs');
const out = process.argv[2];
process.title = process.argv[3];
process.stdout.write('\x1b[?2004h');
process.stdin.setRawMode(true);
process.stdin.resume();
process.stdin.on('data', (d) => fs.appendFileSync(out, d));
setTimeout(() => process.exit(0), 60000);
