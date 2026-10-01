// After `npm run build`, this copies dist/ to ../app/static/viz/
// so Flask can serve the bundle at /static/viz/

import { rmSync, cpSync, mkdirSync, existsSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const distDir = join(__dirname, 'dist');
const targetDir = join(__dirname, '..', 'app', 'static', 'viz');

if (!existsSync(distDir)) {
  console.error('!! dist/ does not exist. Run `npm run build` first.');
  process.exit(1);
}

// Wipe target so old assets don't linger
if (existsSync(targetDir)) {
  rmSync(targetDir, { recursive: true, force: true });
}
mkdirSync(targetDir, { recursive: true });

// Copy everything from dist/ -> app/static/viz/
cpSync(distDir, targetDir, { recursive: true });

console.log(`Copied dist/ -> ${targetDir}`);
