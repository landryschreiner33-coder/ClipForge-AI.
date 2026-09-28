import { expect, test } from "../fixtures";

// Checks that Autopilot and publishing only take orders from ClipFoundry's own page on this computer.
// The probes name jobs and posts that do not exist, so even a broken guard could not change anything.

test("reads work from this computer", async ({ request }) => {
  for (const path of ["/api/autopilot/status", "/api/publish/accounts", "/api/autopilot/scheduled?view=upcoming"]) {
    expect((await request.get(path)).status(), path).toBe(200);
  }
});

test("state-changing calls without the app's header are refused", async ({ request }) => {
  for (const path of ["/api/autopilot/jobs/e2e-no-such-job/cancel", "/api/publications/e2e-no-such-post/cancel", "/api/autopilot/scheduled/e2e-no-such-item/cancel"]) {
    const res = await request.post(path);
    expect(res.status(), path).toBe(403);
    expect((await res.json()).detail).toContain("ClipFoundry page");
  }
});

test("requests for another host name are refused (DNS rebinding)", async ({ request }) => {
  for (const path of ["/api/autopilot/status", "/api/publish/accounts"]) {
    const res = await request.get(path, { headers: { Host: "clipfoundry.example" } });
    expect(res.status(), path).toBe(403);
  }
});
