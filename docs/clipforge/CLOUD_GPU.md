# A cloud computer for pictures and video (RunPod)

Making pictures and video clips on a laptop is slow, even on a fast Mac. Since Nov 13 2026 ClipForge can send that
work to a computer with a big graphics card that you rent by the hour, for example on RunPod. Everything else (your
videos, your projects, the voice, the AI helper) stays on your own computer.

**What Landry asked for (Nov 13 2026):** "Is there a way I can have this run on a free server or something cheap
that's not on my computer so it runs faster", then "Do step 4" (connect ClipForge to it).

## The short version

1. Rent a RunPod "pod" with an RTX 5090 (or a cheaper RTX 4090) and a 100 GB disk, using RunPod's ComfyUI template.
2. Copy its address into ClipForge: Settings, Pictures, video, voice, "A cloud computer".
3. Put the models on it with the command ClipForge gives you (copy, paste, Enter).
4. Make your shorts as usual. Pictures and clips now come from the cloud computer.
5. **Press Stop in RunPod when you finish.** A pod that is on costs money every hour, even when nobody uses it.

## Step by step (the same steps are in the app)

1. Go to [runpod.io](https://www.runpod.io) and make an account. In **Billing**, add some credit ($10 is plenty to
   try it).
2. Press **Pods**, then **Deploy**. Choose **Community Cloud** (it is cheaper).
3. Pick an **RTX 5090**: it is the fastest. An **RTX 4090** costs less and works well too. Any card with at least
   24 GB is fine. RunPod shows the price per hour next to each one.
4. Press **Change Template**. For an RTX 5090 pick **ComfyUI Blackwell Edition**. For an RTX 4090 pick **ComfyUI**.
   (The 5090 is a newer kind of card that needs the Blackwell version.)
5. Press **Edit Template** and set the **Volume Disk** to **100 GB**, so the models fit and stay there when the pod is
   stopped. Save it.
6. Press **Deploy On-Demand**. Wait until your pod says **Running** (a few minutes the first time).
7. Press **Connect**, then the button for port **8188**. ComfyUI opens in a new tab. Copy that tab's address from the
   top of your browser. It looks like `https://abc123xyz-8188.proxy.runpod.net`.
8. In ClipForge: **Settings**, **Pictures, video, voice**, choose **A cloud computer**, paste the address and press
   **Save and check**. It should say **Connected** and name the graphics card.
9. Put the models on it. Under **Pictures** and **Video clips**, press **Put it on your cloud computer** next to a
   model. ClipForge shows a command:
   - In RunPod, press **Connect** on your pod, turn on the **Web Terminal** and open it (or open **JupyterLab**, then
     File, New, Terminal).
   - Press **Copy the command** in ClipForge, click in the terminal, paste it and press Enter.
   - Wait until it says **Done**. The cloud computer downloads the files itself, so your own internet is not used.
   - Back in ClipForge, press **I ran it: check again**.
   With an RTX 5090 or 4090, ClipForge recommends Z-Image Turbo for pictures, and Wan 2.2 makes the clips.
10. Make a test picture in the same Settings page. Then use the animated-shorts maker as usual.

**When you finish, press Stop on your pod in RunPod.** Start it again next time: its address stays the same and the
models are still there. A stopped pod's 100 GB disk still costs a little (RunPod charges about $0.20 per GB a month
for a stopped pod's disk, so about $20 a month). If you will not use it for a long time, press **Terminate** instead:
that costs nothing, but the models are deleted and you put them back next time.

Keep the address to yourself: anyone who has it can use your cloud computer while it is on.

### When it says something is wrong

| ClipForge says | What it means | What to do |
|---|---|---|
| Nothing answered at the address you saved | The pod is off, or the address is wrong | Start the pod in RunPod (Pods, Start), wait, press Check again |
| Your cloud computer is there, but its ComfyUI is not ready (it answered 502, 524 …) | The pod is starting, or ComfyUI on it is still loading | Wait a few minutes and press Check again |
| RunPod has nothing running at this address | The pod was terminated, or the address is for another port | Copy the address again from Connect (port 8188) |
| That address answers, but it is not ComfyUI … use the one for port 8188 | You copied another port's address (JupyterLab is 8888) | Copy the one for port 8188 |
| Your cloud computer said no (it answered 401 or 403) | It wants a password or key, or the one kept is wrong | Open "Does it need a password?" (it says "Key: kept on this computer" when one is kept) and type it |
| Your cloud computer stopped answering for 3 minutes | It was stopped (or ran out of credit) while working | Start it again in RunPod; make the picture again |
| Waiting for your cloud computer: it is making another picture or clip | Another picture or clip is being made | Nothing: it starts by itself when the other is done |

| Your cloud computer did not pass the request on to ComfyUI (it answered 502 …) | It answered the check, then not a question about its models (it is stopping or starting) | Check in RunPod that it is on, wait a minute, press Check again |
| The ComfyUI in Settings changed while this waited for its turn | You chose another ComfyUI while the picture waited | Make it again |

Short hiccups (RunPod's gateway answering 502 or 524 for a moment, a dropped connection) are waited out and tried
again by themselves, also when ClipForge asks which models the cloud computer has (so a hiccup never reads as "not on
it yet").

## What goes to the cloud computer

- The words for each picture or clip (the prompt, the "avoid" words, the size, the seed), and the picture a clip
  starts from. Nothing else: not your videos, projects, scripts, voice-overs, accounts or the AI helper's memory.
- What it makes comes back to ClipForge and is kept here (engines/made, or with the short that uses it).
- ComfyUI on the cloud computer keeps its own copy of each picture and clip it made (its output folder) and of each
  picture a clip started from (its input folder) until you delete them or terminate the pod. RunPod's privacy rules
  apply to that computer.
- If you set a key, it is kept locked on your computer (like the app's other keys) and sent only to the address you
  saved, never anywhere else. It is never shown again in Settings. When you save a different cloud computer's
  address, the key is removed (enter it again if that one needs it). On a Mac, a locked login Keychain cannot keep a
  key: Settings says so and saves nothing.

## How it works (for whoever changes it next)

- **Settings:** `engines_comfyui = "remote"`, `engines_remote_url` (https only, except plain http to this computer
  for tests; no user name in the address), `engines_remote_key` (printable ASCII only, since it goes in a header as it
  is; sealed like the other secrets, shown as `********`). The address and key are `ACTION_ONLY_KEYS`: only
  `POST /api/engines/remote` (ClipForge's own page) sets them, never `PUT /api/settings`, so no other page can point
  the key somewhere else; a new address (another host, scheme or port: two tunnels on this computer are two
  computers) drops the kept key (even one a locked Keychain cannot read right now), and an
  address and key are saved together or not at all. Whoever has the address can use the cloud computer, so it is
  kept off the pages other sites could read: `GET /api/settings` shows it as `********` (`config.UNSHOWN_KEYS`),
  `GET /api/engines` answers this computer only, and the words on other pages (a short's maker, its notes, its
  errors) name the cloud computer by its graphics card, never by its address. The local choices stay the default.
- **`clipfoundry/engines/remote.py`:** `normalize()` turns what was pasted (a bare pod ID, an address without
  https://, ComfyUI's page with `index.html`) into the address; `check()` asks `/system_stats` (cached 15 s, never
  raises) and turns every answer into plain words (the table above); `machine()` lets `makers.ranked/fit` pick the
  model that suits the cloud computer's graphics card; `turn()` makes this app's jobs take turns for the cloud
  computer (instead of this computer's graphics lock); `command_for()` / `download_command()` build the copy-paste
  command.
- **The command** is plain bash, safe to paste twice: each file comes from its pinned Hugging Face address (the same
  pins as `catalog.py`), downloads to a `.part` file that a second run resumes, is checked by size and SHA-256 before
  it gets its name (a damaged one is deleted), and never replaces a different file of the same name. It goes into
  the folders ComfyUI names at `/internal/folder_paths`, or, when the cloud computer did not answer, into the first of
  RunPod's usual ComfyUI model folders that exists. Every value in it is shell-quoted.
- **`clipfoundry/engines/comfy.py`:** `use_remote(base, key)` registers the one cloud address; a client for that
  address sends `Authorization` (Bearer, or Basic for `name:password`) on every request and on the websocket, and
  nowhere else. For a cloud address only: uploads and downloads are tried again (3 times) on gateway answers and
  dropped connections; while waiting for a job, failures are waited out for up to 3 minutes (`LOST_S`) before it gives
  up in plain words; a graph is **never sent twice** (a retried `/prompt` could make it twice and charge twice).
  Questions about which models and nodes it has are asked again on a gateway answer or a dropped connection too;
  one that still gets no answer from ComfyUI (or RunPod's 404 for a pod stopped since the check) says so in plain
  words instead of "not on it yet" or "this ComfyUI lacks ...". A job's history is asked once per look: the job
  waits outages out itself (`LOST_S`) and looks at Stop between questions.
  A job waiting for its turn checks Settings again when its turn comes and stops if another ComfyUI was chosen
  meanwhile; the note next to each file names the model that made it, not whatever is chosen afterwards.
  A job the pod forgot (its ComfyUI restarted: the job is in neither its queue nor its history) ends in plain words
  instead of waiting out the time limit; it is looked for after an outage and every 30 s (`LOST_CHECK_S`), and the
  history is asked once more before calling it lost. `makers.mode()` forgets the cloud registration whenever another
  ComfyUI is chosen, so a ComfyUI on this computer at the same address never gets the key or the waiting. This
  computer's ComfyUI behaves exactly as before.
- **Not offered for the cloud computer:** ClipForge's own Download and Remove buttons (it cannot reach the cloud
  computer's disk; the routes refuse with what to do instead). The voice always runs on this computer.
- **Routes:** `POST /api/engines/remote` `{url, key?}` (app header; a missing key keeps the kept one, `""` removes
  it), `GET /api/engines/remote/command?model=&agreed=` (this computer only). Both 404 in the online studio.
- **Pages:** Settings shows the cloud panel, the cost warning, the guide and the command dialog; the shorts maker says
  "on your cloud computer" instead of "on this computer" (`status()` returns `remote: true`).

## How it was checked

- `tests/test_remote_engines.py` (51 tests) with a stand-in that plays RunPod's proxy in front of the stand-in
  ComfyUI (on, starting, off; 502/524 gateway answers; dropped connections; a key): the address and key rules,
  the key going only to the cloud address (also on the websocket), every check message, a picture and a clip made on
  the cloud computer with the right model for a 24 GB card, hiccups waited out, a pod that stops answering, a job
  never sent twice, a job a restarted pod forgot, taking turns, the Settings routes (only ClipForge's page sets the
  address and key; a key stays with its address; a locked Keychain; keys that cannot be sent; choosing this computer
  again forgets the cloud computer), and the command run for real with bash (checked files, a
  resumed download, a damaged one deleted, a different file left alone, wget instead of curl, the folder found by
  itself, quoting that cannot be broken out of). Each rule was also broken on purpose to see a test fail.
- The real-machine check (`scripts/local_engines_check.py --remote`, on GitHub's Linux and Mac machines) uses the real
  ComfyUI it set up as a cloud computer with a key: the check, the model folders, a websocket with the key's headers,
  the model-free graphs, the command run for real for the smallest model file (which ComfyUI must then list), and on
  Linux a real picture made in cloud mode.
- **Not checked from here:** a real RunPod pod (it needs Landry's account and costs money), RunPod's current menus
  and template names, and real speeds on an RTX 5090 or 4090. The first time Landry connects, a test picture in
  Settings checks the whole path.
