// Starts the Playwright MCP server declared in .mcp.json.
// Cloud sessions ship a Chromium at /opt/pw-browsers/chromium and block browser downloads, so use it when present;
// elsewhere (your PC) the server uses its own browser. If that is missing, its error names the one-time install
// (`npx @playwright/mcp@latest install-browser chrome-for-testing`): the browser has to match the server's
// Playwright version, which `npx playwright install chromium` does not guarantee.
import { existsSync } from 'node:fs';
import { spawn } from 'node:child_process';

const args = ['-y', '@playwright/mcp@latest', '--browser', 'chromium'];
const preinstalled = '/opt/pw-browsers/chromium';
if (existsSync(preinstalled)) args.push('--executable-path', preinstalled);

const windows = process.platform === 'win32';
const server = spawn(windows ? 'npx.cmd' : 'npx', args, { stdio: 'inherit', shell: windows });
server.on('exit', (code) => process.exit(code ?? 1));
