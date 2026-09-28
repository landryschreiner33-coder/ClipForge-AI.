import { baseURL } from "./playwright.config";

/** Fails fast, with what to do, when ClipFoundry is not running where the tests expect it. */
export default async function globalSetup(): Promise<void> {
  let health: { version?: string; data_dir?: string };
  try {
    const res = await fetch(`${baseURL}/api/health`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    health = await res.json();
  } catch (e) {
    throw new Error(
      `ClipFoundry is not reachable at ${baseURL} (${(e as Error).message}).\n` +
        "Start it first (double-click start.bat and leave the window open), then run the tests again.\n" +
        "If it runs on another port, set CLIPFOUNDRY_URL, e.g.  set CLIPFOUNDRY_URL=http://127.0.0.1:8766",
    );
  }
  console.log(`\n  Testing ClipFoundry ${health.version} at ${baseURL}\n  Data folder: ${health.data_dir} (read only)\n`);
}
