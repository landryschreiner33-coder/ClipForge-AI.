# Processing measurements and server advice

The new `/api/office/performance?days=7` report and `python -m clipfoundry performance --days 7` command measure
active intervals between actual persisted job transitions. They group by job kind, stage and robot, with sample
count, total, median and p95 seconds. Waiting, unfinished stages and missing history are excluded. Repeated resume
intervals are counted separately. Parallel active times overlap; their sum is not wall-clock duration. History is
bounded to 14 days / 20,000 events, so this is a troubleshooting view, not a complete long-term profiler.

## What was measured here

The continuation ran on Linux without an NVIDIA GPU. Real FFmpeg rendering used CPU encoding; speech fixtures used
synthetic media and deterministic imported/stand-in transcripts. Platforms and results were local fakes. An earlier
633-case fast test run finished in 424.12 seconds: the largest individual media call rendered, captioned, packaged and checked a multi-cut
clip in 23.33 seconds. These are test observations under concurrent workload, not an RTX 3050 benchmark.

The complete-loop run measured these active intervals:

| Stage | Intervals | Total active seconds | Median seconds | p95 seconds |
| --- | ---: | ---: | ---: | ---: |
| Rendering (CPU) | 6 | 107.81 | 13.23 | 46.82 |
| Final quality checks | 4 | 13.00 | 3.27 | 4.35 |
| Caption preparation | 3 | 5.99 | 2.09 | 2.31 |

These are stage intervals, not complete-clip averages. Rendering resumes and transitions split intervals. Live
capture also took 60.74 seconds of active intervals, including recording time; that is not a hardware throughput
measurement. The transcribe-labelled stage used a deterministic stand-in, so its timing is not a Whisper benchmark.

The complete-loop browser run also exports actual production stage transitions to
[processing-timings.json](../design/robot-office/screenshots/processing-timings.json). Its media jobs, render/check
handlers, scheduler and restart recovery are real; discovery, account APIs, transcripts and result maturity are test
fixtures. Public due times are advanced only on that isolated server. The report cannot measure real download
speed, Whisper model throughput, paid services or internet upload time.

## Recommendation

Keep the existing PC for now. This session supplies no evidence that renting a server would materially beat its
RTX 3050. Rendering is the largest observed local media operation here, while real GPU transcription has not been
measured. A basic CPU VPS could be slower at both. A GPU server might improve throughput, but its price, GPU memory,
model availability, bandwidth and the size of your real videos must be compared with your PC’s measured timings.

A server could help continuous operation if the PC sleeps, shuts down or loses connectivity. First test the current
keep-awake setting and worker restart recovery on the PC. Run the explicitly isolated CUDA check in the Windows
guide, separately confirm NVENC in a rendered clip's saved information, process a representative video, and
collect a seven-day timing report using the [separate Windows test copy](WINDOWS_PR14_TEST.md). Compare transcription,
rendering, downloading and upload waits before choosing hardware. GPU calls remain serialized on the existing path;
25 visual robots are responsibilities, not 25 GPU or paid AI processes.

Hosting cannot remove TikTok’s approval/per-post-consent requirements, YouTube project restrictions, access rules,
missing metrics or posting limits. It would also require deliberate account-token setup on the new host; Windows
DPAPI tokens are tied to the Windows account/PC. No server was rented and nothing was deployed.
