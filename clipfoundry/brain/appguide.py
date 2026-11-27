"""What ClipForge AI knows about ClipForge itself: where things are and how to do them, in plain words
(docs/clipforge/CLIPFORGE_AI.md, "What it knows").

Before this guide the assistant knew editing craft (brain/knowhow.py) but nothing about its own app, so "how do I
clip a live stream?" or "where do I change the captions?" got a guess or a shrug. Each section is one subject a
person asks about: a title, a few short lines that name the page and the buttons as the screen shows them, the other
words a question may use, and the page to open. The library (brain/library.py) picks the sections that fit a
question, for the model's prompt and for the chat's answer when no model is set up.

Every line must be true of this version: it names only pages, buttons and limits that exist. tests/
test_assistant_library.py checks each page address against the app's own page list.
"""
from __future__ import annotations

from dataclasses import dataclass

HEADER = "How ClipForge works (built in; name the page and the button, never invent a feature):"


@dataclass(frozen=True)
class Section:
    id: str
    title: str
    lines: tuple[str, ...]
    words: tuple[str, ...] = ()
    page: str = ""          # a key of PAGES: the page a chat answer links to

    @property
    def text(self) -> str:
        return f"{self.title}: " + " ".join(self.lines)


# Every page the assistant can link to: key -> (name as the app shows it, address).
PAGES: dict[str, tuple[str, str]] = {
    "studio": ("Studio", "#/"),
    "projects": ("Projects", "#/projects"),
    "make_clips": ("Make clips", "#/create/clips"),
    "make_video": ("Make a YouTube video", "#/create/video"),
    "make_short": ("Make an animated short", "#/create/short"),
    "text_stories": ("Text Stories", "#/stories"),
    "from_link": ("Make clips from a link", "#/create/link"),
    "live_streams": ("Missions → Live streams", "#/missions/live"),
    "check_video": ("Make → Check a video", "#/create/check"),
    "missions": ("Missions", "#/missions"),
    "missions_activity": ("Missions → Activity", "#/missions/activity"),
    "missions_sources": ("Missions → Permissions & sources", "#/missions/sources"),
    "styles": ("Brain → Styles", "#/brain/styles"),
    "memory": ("Brain → Memory", "#/brain/memory"),
    "talk": ("Talk to ClipForge AI", "#/brain/talk"),
    "agents": ("Brain → Agents", "#/brain/agents"),
    # the space studio's Brain (2026-11-19): Memory, Styles, Talk to AI, Agents, Decisions, and More for the rest
    "example_videos": ("Brain → More → Example videos", "#/brain/example-videos"),
    "notes": ("Brain → Memory → Knowledge map", "#/brain"),
    "example_notes": ("Brain → More → Example notes", "#/brain/examples"),
    "skills": ("Brain → More → Skills", "#/brain/skills"),
    "decisions": ("Brain → Decisions", "#/brain/decisions"),
    "results": ("Brain → More → Performance history", "#/brain/results"),
    "publishing": ("Publishing", "#/publishing/review"),
    "publishing_scheduled": ("Publishing → Scheduled", "#/publishing/scheduled"),
    "publishing_published": ("Publishing → Published", "#/publishing/published"),
    "publishing_problems": ("Publishing → Problems", "#/publishing/problems"),
    "publishing_results": ("Publishing → Results", "#/publishing/results"),
    "accounts": ("Accounts", "#/accounts"),
    "office": ("Office", "#/office"),
    "team": ("Office → Team", "#/office/team"),
    "settings_appearance": ("Settings → Appearance", "#/settings/appearance"),
    "media_sources": ("Settings → Media sources", "#/settings/media"),
    "ai_settings": ("Settings → ClipForge AI", "#/settings/ai"),
    "editing_apps": ("Settings → Editing apps", "#/settings/apps"),
    "makers_settings": ("Settings → Pictures, video, voice", "#/settings/makers"),
    "cloud_computer": ("Settings → Cloud computer", "#/settings/cloud"),
    "connections_setup": ("Settings → Connections setup", "#/settings"),
    "defaults": ("Settings → Defaults", "#/settings/defaults"),
    "integrations": ("Settings → Integrations", "#/settings/integrations"),
    "advanced": ("Settings → Advanced", "#/settings/advanced"),
}

SECTIONS: tuple[Section, ...] = (
    Section("what", "What ClipForge does", (
        "ClipForge turns long videos and live streams into short vertical clips with captions, titles and post "
        "text, edits full YouTube videos from your files, makes animated voice-over shorts, and posts to your "
        "YouTube and TikTok accounts.",
        "Everything starts from the Make button in the top bar or the Studio's Make tab: Make clips, Make a YouTube "
        "video, Make an animated short, Make a text story, Clip a live stream. The Studio's Working on tab shows "
        "what is being made, "
        "what's going on and the next post.",
        "It runs on this computer; your videos stay here unless you post them."),
        ("clipforge", "app", "program", "features", "can it", "what can", "overview", "start", "begin", "new here",
         "how does it work"), "studio"),
    Section("make_clips", "Making clips from a video", (
        "Make → Make clips. Drop a video or paste a link, then choose Highlights (the strongest short moments), "
        "Full story (one whole clip per story) or Story parts (each story cut into Part 1, Part 2 and so on).",
        "Customize captions and framing changes this project only; the box Used from your Brain shows which style, "
        "skill or note decides each choice.",
        "Make clips only keeps the clips here to review and download. Make & upload clips also posts them to the "
        "channels you tick.",
        "The project page then lists the clips, best first, each with its Viral Potential score and why it was "
        "picked."),
        ("clip", "clips", "clipping", "highlights", "full story", "story parts", "podcast", "moments",
         "shorts from", "turn into", "make clips", "upload a video", "drop"), "make_clips"),
    Section("links", "Clips from a link", (
        "Paste a public video link on Make clips (Video link). Your own transcript file works only with a video "
        "file: Make clips → add the video with its transcript.",
        "Only public videos work: nothing private, members-only or behind a sign-in.",
        "A live link is recorded like a live stream."),
        ("link", "links", "url", "youtube link", "paste", "download", "import", "twitch vod", "vod", "from youtube"),
        "from_link"),
    Section("live", "Clipping a live stream", (
        "Make → Clip a live stream, or Missions → Live streams. Paste one or more links, one per line, up to 10: a "
        "Twitch or Kick channel, a YouTube live video or a channel's live page.",
        "ClipForge records while the stream is live and cuts clips from the last 15 minutes as it runs; three "
        "streams are clipped at the same moment and more take turns.",
        "A channel that is not live yet waits for the stream for up to a day. Stop recording on the stream's card "
        "ends it and clips the whole recording.",
        "With Make & upload clips, good clips post during the stream, at least the Minimum gap apart (30 minutes "
        "unless you change it). Recording stops at the Largest source limit in Settings → Advanced (8 GB and 240 "
        "minutes unless you change it)."),
        ("live", "live stream", "livestream", "stream", "streams", "streaming", "twitch", "kick", "while live",
         "going live", "record", "recording", "broadcast", "streamer"), "live_streams"),
    Section("predictor", "The predictor", (
        "Every clip is predicted after it renders: a viral score from 0 to 100, the hook (the first 3 seconds), how "
        "much is watched on average and how many stay to the end (a hold curve), the strongest moment, and a "
        "heatmap of vision, sound, language, attention and memory second by second.",
        "The clip editor's Viral predictor card lists fixes it tried on the clip first (start later, end earlier, "
        "remove pauses, captions, the hook on screen, punch-ins, louder sound); Add to my edit puts one in, then "
        "Save and render.",
        "Make → Check a video predicts any video you upload, on this computer.",
        "It is an estimate, not a promise of views. Once your posts have results, Publishing → Results shows how "
        "well it matched and it calibrates itself. Its on/off switch is in the AI settings."),
        ("predictor", "predict", "prediction", "predicted", "heatmap", "=viral score", "=viral predictor",
         "=check a video", "=will it go viral", "=how will it do", "=hold rate", "=retention curve", "=hook score",
         "=strongest moment"),
        "check_video"),
    Section("clip_length", "How long clips are", (
        "Settings → Defaults sets the Shortest clip, the Ideal clip length and the Longest clip in seconds, and "
        "how many clips a video gives.",
        "Make clips again on a project (its menu) makes new clips from the same video with other lengths.",
        "You can also tell me: “remember: clips should be at least 40 seconds” and clip picking follows it.",
        "A story clip is never longer than five minutes; a longer story is split into parts."),
        ("length", "long", "longer", "short", "shorter", "seconds", "duration", "too short", "too long", "how many "
         "clips", "number of clips", "clip count", "minimum", "maximum"), "defaults"),
    Section("clip_editor", "Changing one clip", (
        "Open a clip from its project to reach the clip editor. Trim sets the start and the end.",
        "Captions: the caption style, position and size, Highlight each word as it is spoken, key words in their "
        "own colour, Burn captions into the video, and the On-screen hook with how long it shows.",
        "Layout: what the framing follows (Auto, Center, Face, Active speaker, Screen content or a position you "
        "choose), Fill (crop) or Fit (blurred background), and Zoom.",
        "Audio: Normalize loudness and cutting “um” and “uh”. Post text: the title, the post text and the "
        "hashtags.",
        "Save and render makes the new file; nothing changes until then."),
        ("editor", "clip editor", "trim", "caption style", "layout", "crop", "zoom", "fit", "fill", "blurred",
         "render", "re-render", "fix a clip", "change a clip", "edit a clip", "save and render"), "projects"),
    Section("framing", "Framing and what the picture follows", (
        "Each clip's framing follows Auto unless you choose: Auto looks for the speaker, a face, the screen or "
        "the moving action and keeps it in the vertical frame.",
        "Fill (crop) fills the phone screen; Fit (blurred background) shows the whole wide picture with a blurred "
        "copy behind it.",
        "Story clips keep the whole picture still and centred with the captions above it.",
        "Change it for one clip in the clip editor under Layout, or for a new project under Customize captions "
        "and framing."),
        ("framing", "frame", "crop", "cropped", "vertical", "9:16", "tracking", "follow", "face cam", "facecam",
         "gameplay", "split", "split view", "split screen", "whole picture", "cut off", "zoomed"), "projects"),
    Section("scores", "Scores and why a clip was picked", (
        "Viral Potential is ClipForge's own 0-100 estimate used to rank clips. It is not a promise of views.",
        "It measures the hook, the payoff, whether the clip stands alone, emotion, pacing and more; each clip's "
        "page shows the factors and the reasons, including what your Brain added or took away.",
        "Clips under the lowest score you allow are left out, but the best one is always kept."),
        ("score", "scores", "viral potential", "rating", "ranked", "why", "picked", "chosen", "points", "estimate",
         "number", "percent", "how good"), "projects"),
    Section("make_video", "Making a YouTube video", (
        "Make → Make a YouTube video. Drop your clips and pictures, write your idea in your own words, then choose "
        "Ask me questions or Just do it.",
        "ClipForge AI plans the video with you; Build my video makes a rough cut with a preview.",
        "On the video's page, change it by hand or tell ClipForge AI what to change; every change is a new version "
        "you can go back to. Render makes the full-quality file and Download gives you that file.",
        "A script you drop is followed line by line, using the cleanest take of each line."),
        ("youtube video", "full video", "long form", "long-form", "edit my video", "footage", "rough cut", "script",
         "plan", "build my video", "vlog", "render", "version", "versions", "timeline"), "make_video"),
    Section("video_timing", "A full video's speed, slow motion, freeze frames and camera moves", (
        "On the video's page, pick a clip in Sequence. Speed goes from Very slow (25%) to Four times; Speed ramp "
        "has Slow motion in the middle, Fast, slow, fast, Slow down to the end and Speed up to the end. A voice "
        "keeps its pitch.",
        "Split or freeze has Freeze here and Hold the last frame: a freeze frame is a clip of its own that holds "
        "for 2 s unless you change Holds for, and the room's sound plays under it.",
        "Camera move (recordings, freeze frames and photos): Slow zoom in, Slow zoom out, or Pan left, right, up or "
        "down.",
        "On a video you can also tell me: “put clip 3 in slow motion”, “freeze the last frame for 2 seconds”, "
        "“slowly zoom in on clip 2”."),
        ("speed", "slow motion", "slow-mo", "slowmo", "slow down", "speed up", "faster", "slower", "fast forward",
         "speed ramp", "ramp", "freeze", "freeze frame", "hold the frame", "still frame", "zoom in", "zoom out",
         "slow zoom", "pan", "ken burns", "camera move", "2x"), "projects"),
    Section("video_sound", "A full video's sound and music", (
        "On the video's page, Sound lists the music, voiceovers and effects; Change on each one sets its volume, "
        "the fades, Mute, Dips while people speak and Loop.",
        "Music set to Loop that plays to the end has End on the last frame: it starts inside the music and fades in, "
        "so its own ending plays as the video ends. ClipForge's own music does this unless you untick it; your own "
        "songs start at their start unless you tick it.",
        "Cuts between two recordings cross over so they never click, and titles, photos and silent clips get the "
        "room sound of the nearest recording instead of silence.",
        "On a video you can also tell me: “end the music on the last frame” or “lower the music while I'm "
        "talking”."),
        ("music", "song", "songs", "soundtrack", "background music", "fade", "fade in", "fade out", "loop",
         "looping", "last frame", "end on the last frame", "music ends", "cut off", "ending", "room tone",
         "room sound", "click", "clicks", "dips", "ducking", "voiceover track", "sound panel"), "projects"),
    Section("make_short", "Making an animated short", (
        "Make → Make an animated short. Paste my script or Write it for me (a topic, a tone and a length).",
        "Choose the look, the voice (Hear it plays a sample), the speed, the music and the captions, and camera "
        "moves or animated pictures, then press Make the short.",
        "The pictures and the voice are made on this computer by the makers in Settings → Pictures, video, voice, "
        "or on a rented cloud computer (Settings → Cloud computer).",
        "The short's page has a Scenes panel to change one picture or one line and make it again."),
        ("animated", "animation", "short", "faceless", "voice over", "voiceover", "ai video", "ai pictures",
         "story short", "script", "narration", "scenes", "cartoon"), "make_short"),
    Section("text_stories", "Making a text story", (
        "+ Make → Make a text story: a text-message story (a phone chat whose bubbles pop up one at a time over "
        "satisfying or gameplay video, each message read aloud in its sender's voice) or a narrated story (title "
        "card, big captions). Up to 10 minutes.",
        "Chat: one message a line, Name: message; Me is whose phone it is (blue, right). Then People and voices, "
        "Background, Look and sound (dark, light, green; pace; pop sounds), Preview, Export.",
        "Paste it, or ClipForge AI writes it from a topic and revises it. Voices: Hear, speed, tone, pronunciations, "
        "a favourite voice per style.",
        "Backgrounds: upload, your videos, free footage or Let ClipForge pick. Export: 1080 × 1920, Download, Open "
        "in the editor."),
        ("text story", "text stories", "reddit story", "story video", "narrated story", "gameplay background",
         "text message story", "text messages", "imessage", "chat story", "fake text", "texting story", "bubbles",
         "cooking background", "satisfying cutting",
         "minecraft parkour", "subway surfers", "satisfying", "voice style", "pronunciation", "tts", "background "
         "video"), "text_stories"),
    Section("projects", "Projects, downloads and deleting", (
        "Projects lists everything you made, with filters for Clips, Full videos and Animated shorts, and search.",
        "Open a project to preview, download or post its clips.",
        "The trash button on a project's card deletes it: a window first lists what goes and what stays, and "
        "nothing is deleted until you confirm. A deleted project cannot be brought back.",
        "I can find, open, rename or delete a project for you; deleting always asks first."),
        ("project", "projects", "library", "find", "where is", "download", "save", "export", "delete", "remove",
         "trash", "rename", "my videos", "my clips", "files"), "projects"),
    Section("publishing", "Posting to YouTube and TikTok", (
        "Connect your channels on Accounts (Add YouTube account, Add TikTok account); add as many as you have.",
        "Prepare post on a clip shows the exact file with its title, post text and hashtags; tick the accounts and "
        "press a platform's button to post it now.",
        "Publishing shows every post (Needs review, Scheduled, Published, History, Problems, Results); posts "
        "Autopilot plans on its own wait under Needs review for your OK.",
        "YouTube clips upload by themselves only for a video you added with Make & upload clips (on Make clips or in "
        "Missions), once each passes its final check; a TikTok post always waits for your OK on the clip's Prepare "
        "post, where the accounts you chose are ticked.",
        "A failed post is under Publishing → Problems with the reason and what to do."),
        ("post", "posts", "posting", "publish", "upload", "uploads", "schedule", "scheduled", "queue", "tiktok",
         "youtube", "shorts", "channel", "channels", "account", "connect", "reconnect", "failed", "problem",
         "automatic", "auto upload"), "publishing"),
    Section("accounts", "Accounts and connections", (
        "Accounts lists your YouTube and TikTok accounts. Reconnect fixes an expired sign-in for that account "
        "only; Make default is used when a post names no account; Disconnect stops posts to that account.",
        "The keys for your own YouTube and TikTok developer apps are under Settings → Connections setup."),
        ("account", "accounts", "sign in", "login", "log in", "connect", "connection", "reconnect", "disconnect",
         "expired", "channel", "default account", "api key", "keys"), "accounts"),
    Section("autopilot", "Missions and Autopilot", (
        "Missions is where ClipForge works on its own: add a video or live stream links there with Make & upload "
        "clips and it makes, checks and posts the clips.",
        "Missions → Activity shows what it did and why; Permissions & sources says what it may use.",
        "Stop all jobs holds everything at once and Resume continues; the Autopilot status in the top bar shows "
        "what is running."),
        ("autopilot", "missions", "mission", "automatic", "hands off", "by itself", "on its own", "stop all",
         "emergency", "pause", "resume", "activity", "jobs", "queue", "running"), "missions"),
    Section("brain", "The Brain: what ClipForge AI learns from", (
        "Brain → Memory is what I remember about how you like things; Skills are imported guides; Notes and "
        "Example notes are your own written advice; Example videos and Styles are looks to copy.",
        "Clip picking and editing read all of them on this computer; titles, post text and my answers read your "
        "memories and switched-on skills, never your notes or example notes as you wrote them. What you told me "
        "wins over a skill, and a skill wins over my built-in know-how.",
        "Once posts have real numbers, I compare which kinds of moment did better and keep it as a memory that "
        "starts “From your results:”. Clip picking follows it until you switch it off or forget it.",
        "Brain → Decisions shows what the Brain changed, and Brain → More → Performance history how your posts "
        "did."),
        ("brain", "learn", "learns", "teach", "train", "knowledge", "smarter", "improve", "what do you use",
         "how do you decide", "data", "results", "what works", "performance", "numbers", "feedback"), "memory"),
    Section("memory", "Teaching ClipForge AI and its memory", (
        "Tell me in any chat: “remember: …”, “always …” or “never …”. Add “for this video” to keep it to "
        "one video.",
        "Ask “what do you know?” to see it, and say “forget …” to remove something.",
        "Brain → Memory lists every memory with where it was used; you can edit it, turn it off or forget it, and "
        "Export or Import the whole brain as a file.",
        "Memories about clips (what you like, what to avoid, how long) steer which moments are picked, and the "
        "clip says so."),
        ("remember", "memory", "memories", "forget", "teach", "preference", "preferences", "rule", "rules",
         "always", "never", "import", "export", "brain file", "backup", "what do you know"), "memory"),
    Section("skills", "Skills", (
        "Brain → More → Skills imports skill files (JSON or Markdown). You see what a skill would change, what it "
        "does not apply and anything it refused, then switch it on.",
        "A switched-on skill sets its editing choices for new projects, and I read its advice when I pick clips, "
        "write titles and post text, and answer you.",
        "Switch all on turns every imported skill on at once. A skill never runs commands and never posts."),
        ("skill", "skills", "import", "preset", "presets", "guide", "guides", "playbook", "switch on", "turn on",
         "enable", "json"), "skills"),
    Section("notes", "Notes, example notes and example videos", (
        "Brain → Memory → Add knowledge → Add note writes advice for the Brain, with the platform or subject it "
        "is for, and the Knowledge map shows it; Brain → More → Example notes describe a video you like and why "
        "it worked.",
        "Brain → More → Example videos takes a video you like: ClipForge measures its pacing, captions, framing "
        "and sound, and you choose what new projects reuse.",
        "Notes stay on this computer: they shape clip picking here and are never sent to an online model."),
        ("note", "notes", "example notes", "example videos", "example video", "reference", "inspiration",
         "copy the style", "like this video"), "notes"),
    Section("styles", "Styles", (
        "A style is a saved set of editing choices: the captions, the framing, the pacing and the sound.",
        "Brain → Styles lists them; My saved style is used for new projects unless you pick another on Make clips.",
        "Changing a style affects new projects only."),
        ("style", "styles", "look", "saved style", "template", "templates", "preset", "default look", "brand"),
        "styles"),
    Section("ai_model", "The model behind ClipForge AI", (
        "Settings → ClipForge AI chooses what answers: the built-in model (free, runs on this computer), Ollama or "
        "LM Studio on this computer, or an online service with your own key.",
        "The built-in model has three levels: Basic (about 1.6 GB), Standard (about 5.2 GB) and Pro (about 15.4 "
        "GB). A bigger level understands more and answers better; Pro needs about 32 GB of memory.",
        "Without a model I still answer from my built-in know-how and this guide, remember what you teach me and "
        "pick clips by rules.",
        "With an online service, only words are sent (the conversation, memories and know-how that fit), never "
        "your videos or their sound."),
        ("model", "models", "ai", "smarter", "dumb", "better answers", "built-in", "builtin", "ollama", "lm studio",
         "openai", "claude", "anthropic", "key", "download", "level", "basic", "standard", "pro", "offline",
         "local", "private", "privacy", "sent", "internet"), "ai_settings"),
    Section("agents", "Helper agents", (
        "Brain → Agents adds helpers with their own instructions; I hand one a job when its subject comes up, "
        "and you talk to one with “@Name …”.",
        "A helper only reads what I pass it and can look things up; it never changes or deletes anything."),
        ("agent", "agents", "helper", "helpers", "assistant", "specialist", "ask the"), "agents"),
    Section("makers", "Pictures, video and voice makers", (
        "Settings → Pictures, video, voice sets up the makers for animated shorts: pictures, moving pictures and "
        "the voice, all running on this computer.",
        "Settings → Cloud computer uses a rented computer for pictures and video instead when this one is too "
        "slow; you pay the rental service, not ClipForge."),
        ("maker", "makers", "pictures", "images", "image", "voice", "voices", "tts", "comfyui", "generate",
         "cloud computer", "gpu", "runpod", "slow", "rent"), "makers_settings"),
    Section("editing_apps", "FilmCraft and EffectCraft", (
        "ClipForge finishes full videos with FilmCraft (a video editor) and EffectCraft (motion graphics). It "
        "fetches both by itself; Settings → Editing apps shows them and can turn that off.",
        "You can also open a video's project in FilmCraft to keep editing by hand."),
        ("filmcraft", "effectcraft", "editing app", "editing apps", "editor app", "premiere", "davinci", "resolve",
         "capcut", "open in", "hand off", "motion graphics"), "editing_apps"),
    Section("settings", "Settings", (
        "Settings has: Appearance (theme, accent colour, layout), Media sources (where extra pictures and clips "
        "come from), ClipForge AI (the model), Editing apps, Pictures, video, voice, Cloud computer, Connections "
        "setup, Defaults (clip length, how many clips, captions, framing, sound), Integrations and Advanced "
        "(limits, storage).",
        "Defaults apply to new projects; a project or a clip you changed keeps its own choices."),
        ("settings", "setting", "options", "preferences", "configure", "default", "defaults", "theme", "dark mode",
         "appearance", "where do i change", "storage", "limits"), "defaults"),
    Section("office", "The Office and the robots", (
        "The Office shows the robot team doing the real work, room by room, and what each one is doing now.",
        "Office → Team renames a robot; a name never changes what it does."),
        ("office", "robot", "robots", "team", "rooms", "rename robot", "workers"), "office"),
    Section("captions_app", "Captions in ClipForge", (
        "Caption styles: Clean, Bold, High energy and Minimal. Bold shows up to three words at a time with a "
        "thick outline, and lights the word being spoken.",
        "Position: bottom (above the part the phone apps cover), middle or top; story clips can put them right "
        "above the picture.",
        "Key words in their own colour and Highlight each word as it is spoken are switches in the clip editor "
        "and in Settings → Defaults.",
        "The words come from what was said; fix a wrong word in the clip editor before rendering."),
        ("caption", "captions", "subtitle", "subtitles", "words on screen", "caption style", "bold", "clean",
         "high energy", "minimal", "highlight", "colour", "color", "wrong word", "spelling", "typo", "bigger",
         "smaller", "font"), "defaults"),
    Section("post_text", "Titles, post text and hashtags in ClipForge", (
        "Every clip gets a title, an on-screen hook, post text and hashtags written from the words said in the "
        "clip, so nothing is promised that the clip does not show.",
        "Change them in the clip editor under Post text or on Prepare post; Write new suggestions writes them "
        "again from the clip's words.",
        "Tell me how you like them (“remember: titles in lower case, no emoji”) and the writer follows it.",
        "In a video's chat, ask me for better titles for a clip and I will read what is said in it first."),
        ("post text", "rewrite", "write new suggestions", "prepare post", "change the title", "edit the title",
         "who writes"), "publishing"),
    Section("troubles", "When something goes wrong", (
        "A project that stopped shows its reason on its card with Try again.",
        "A link that will not import: it must be public and still online.",
        "No model answering: Settings → ClipForge AI shows whether the built-in model is downloaded and running.",
        "A post that failed: Publishing → Problems names the reason. An expired sign-in: Accounts → Reconnect.",
        "Slow on this computer: closing other apps helps; pictures and video can use Settings → Cloud computer."),
        ("error", "errors", "failed", "fail", "broken", "not working", "doesn't work", "stuck", "problem",
         "problems", "wrong", "bug", "crash", "slow", "help", "fix", "trouble", "why did"), "studio"),
    Section("me", "What ClipForge AI can do in this chat", (
        "I answer questions about editing, going viral and ClipForge; find, open, rename and delete projects "
        "(deleting asks first); remember and forget what you teach me; read how your posts did; open any page.",
        "When you ask, I do it: move, cancel, retry, edit, approve or post posts; trim a clip or change its captions, "
        "speed or sound; make clips from a link; add to Missions; write a Text Story; run Autopilot; change editing "
        "choices and posting rules.",
        "Settings → ClipForge AI: do it at once or show an OK button first. Deleting always asks; a TikTok post "
        "waits for your OK on its page (TikTok's rules).",
        "In a video's chat I propose changes to it; they happen when you press Apply.",
        "I can't watch a video here or connect an account; I link the page for that."),
        ("you", "can you", "what can you do", "abilities", "able", "help me", "assistant", "chat", "do for me",
         "who are you"), "talk"),
)
BY_ID = {s.id: s for s in SECTIONS}


def link(section: Section | str) -> dict | None:
    """The button that opens a section's page: {"label", "href"} (None when it names no page)."""
    s = BY_ID.get(section) if isinstance(section, str) else section
    if not s or s.page not in PAGES:
        return None
    name, href = PAGES[s.page]
    return {"label": f"Open {name}", "href": href}
