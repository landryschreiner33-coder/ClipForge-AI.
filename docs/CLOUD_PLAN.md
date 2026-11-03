# ClipFoundry cloud migration plan

Planning checkpoint: November 3, 2026 (America/Chicago). No cloud service has been provisioned and no paid
resource is authorized. The working Mac app and public download website remain unchanged.

## Confirmed owner goals

- Run the studio and scheduled work on a server, independent of the owner's Mac being awake.
- Require login; admit only the owner initially, with a later public release in mind.
- Process more than five hours of source video per day.
- Minimize cost. Target a $0 infrastructure pilot; do not equate this with proven free production capacity.
- A second major change has not yet been specified. Revisit the plan when it is provided.

## Recommended first deployment

Use one Oracle Always Free eligible ARM VM for the API, frontend, database, scheduler and a single CPU processing
slot. Use Supabase's free Auth tier with Google sign-in for identity, restricted to a configured owner subject.
Do not put videos in Supabase's small free storage allocation. Store them on the VM's persistent data volume
initially, with explicit quotas and a verified backup/export path. Serve the studio over HTTPS; use a free
hostname where available, or an existing owner-controlled domain. The existing Sites page remains the download
website and can later link to the authenticated studio.

This is a proposed configuration, not a completed or performance-tested deployment. A free VM must actually
be available in the owner's home region. Reconfirm the account's displayed allowances before provisioning.
Do not provision resources relying on temporary trial credits as if they were permanently free.

Current official Oracle documentation lists 1,500 A1 OCPU-hours and 9,000 GB-hours per month, equivalent to
2 OCPUs and 12 GB RAM, and 200 GB total block storage including boot volumes. Idle instances can be reclaimed;
free capacity can be unavailable. Oracle requires payment-card verification even for Free Tier registration.
Supabase's free Auth supports social OAuth, but free projects can pause after a week of inactivity.

Sources checked November 3, 2026:

- [Oracle allowances, capacity and idle-instance policy](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm)
- [Oracle signup and card verification](https://www.oracle.com/cloud/free/faq/)
- [Supabase free Auth and project limits](https://supabase.com/pricing)

## Application changes needed before internet access

1. Introduce an explicit cloud mode; keep desktop behavior and local profiles intact. Refuse cloud startup if
   identity validation, owner configuration or secret encryption is missing. No unauthenticated fallback.
2. Verify identity on the server for all private API, file, streaming and job endpoints. Validate token
   signature, issuer, audience, expiry and authorized subject. A hidden login screen alone is insufficient.
   Keep public registration disabled. Restrict origins/hosts and preserve request-forgery protection.
3. Add a stable workspace identity and owner association. The current database has global settings and accounts
   keyed by platform, so it is not yet safe for independent public users. The initial single workspace may use
   the existing SQLite database on local persistent disk, isolated to that deployment. Do not share SQLite
   over a network filesystem or use environment-variable switching inside a shared request process.
4. Replace the current loopback-only publishing guard with authenticated cloud authorization in cloud mode.
   Use a configured HTTPS origin for OAuth callbacks, not untrusted request headers. Register web OAuth
   clients/callbacks with the providers and bind each sign-in attempt to its user/workspace/session.
5. Add encrypted Linux credential storage using a separately managed deployment key. The current Linux
   fallback is base64 encoding, not encryption, and is unsuitable for the cloud target. Fail closed when the
   key is unavailable. Keep secrets out of the browser, logs and media-worker payloads.
6. Package the backend and media dependencies in a reproducible Linux ARM64 container. Verify binary-wheel,
   FFmpeg/font and speech-model support on that architecture. Make CPU processing a deliberate configured
   choice; do not weaken the desktop's strict GPU-failure policy or silently lower model quality.
7. Use durable job admission, bounded CPU threads and one heavy processing slot initially. Keep scheduling
   responsive during transcription/rendering. Restart services after failure, with readiness checks and logs.
8. Support authenticated resumable large uploads and private video playback/download. Bound source size,
   temporary disk usage and retained media. Clean regenerable temporary files after jobs; deleting originals
   requires an explicit retention choice. Preserve URL validation and restricted media subprocess protocols.

## Cost and throughput checkpoint

Source-video hours are not billed computing hours. Resolution, speech model, visual analysis, output count,
encoding and retries all affect processing time. Five hours of 8 Mbps source video is approximately 18 GB
before intermediate files and finished clips; unlimited retention is not compatible with a small free disk.

Benchmark representative owner-authorized material on the actual server. Record source duration, resolution,
model/quality settings, clips produced, total wall time, peak memory/disk, failures and stage timings. Measure
the full pipeline, not only transcription. A useful acceptance criterion is completing the expected day's
work within 24 hours with headroom, without compromising the selected quality settings.

If the free CPU cannot keep up, compare a paid CPU host against an optional GPU worker that scales to zero.
Keep login, scheduling and publishing on the persistent host. Give workers only job-scoped inputs/outputs;
keep platform credentials and final publication on the server. Preserve exact-file checks and idempotent
job completion. Transfer time, model startup, idle timeout, persistent storage and backups count toward cost.

[Runpod's billing documentation](https://docs.runpod.io/serverless/pricing) describes flex workers that scale
to zero, with charges during startup, execution and the idle timeout, plus storage. It is a candidate to
benchmark, not a selected or provisioned provider. Spending limits must be enforced at admission, with
conservative in-flight reservations and worker/time limits; billing alerts alone are not hard caps.
Present a measured cost estimate and the exact proposed paid resources before requesting any paid deployment.

## Data migration and cutover

- Back up the original database and media while the local writer is stopped; migrate a copy. Relocate source
  and output paths without changing file bytes, hashes or recorded history. Keep the working Mac installation.
- Reconnect social accounts and service keys on the server. Mac Keychain/Windows DPAPI credentials cannot
  simply be copied to Linux. Preserve selected accounts, audiences, reuse assertions and approval bindings.
- Test with synthetic media and fake platforms first; no real posts as part of automated verification.
- Before live cutover, pause local publishing and inventory in-flight/uncertain uploads. Do not run two
  schedulers against copies of the same active queue. Resume only a reconciled cloud queue; do not replay
  completed posts or guess the result of an interrupted upload.
- Test restore/restart and an authenticated phone session before relying on unattended cloud operation.

## Required verification

- Logged-out, wrong-user, expired-token and direct-file requests cannot read data or start work.
- Owner login, session expiry/logout, reconnect flows and large-file resume work over HTTPS.
- Brain guidance, dynamic framing, captions and raw AAC startup timing retain their existing regressions.
- Job restart does not duplicate renders/publications; platform waits, uncertain outcomes and approval guards
  remain intact. Credential storage and backups can be restored without leaking keys.
- A staged workload measures whether the selected server meets the expected daily volume.

## Before public signup

Implement and verify independent workspace ownership throughout database queries, files, jobs, exports,
credentials and OAuth state. Use a deliberate multi-user database/storage design (for example Postgres and
private object storage), with negative cross-workspace access tests. Add per-user quotas, fair scheduling,
cost controls, account recovery/deletion, abuse controls and appropriate service/privacy terms. Do not enable
public signup merely because the owner's private login works.

## Next owner setup

The owner needs an Oracle Free Tier account and a free Auth project before those services can be configured.
Account creation/card verification happen directly with the provider; never send passwords, card details,
private keys or service credentials through chat. After availability is known, prepare the app changes and
reviewable deployment configuration. No provider account, cloud login or running server exists from this plan.
