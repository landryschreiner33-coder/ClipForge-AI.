# Who can see your clips (selected audiences)

ClipFoundry never makes a clip public. Each platform has one of three settings (Settings → Integrations → *Who can
see it*):

| Setting | YouTube | TikTok |
| --- | --- | --- |
| **Keep on this PC** (default) | Nothing is uploaded | Nothing is uploaded |
| **Only me (staging)** | Uploaded as a **private** video only you can see | Posted as **Only me** (`SELF_ONLY`) |
| **Selected audience** | Uploaded as a **private** video. You then invite your test viewers in YouTube Studio | Posted to **Followers** or **Friends** of a **private** account, either directly (audited app) or through a manual posting package |

**Public, unlisted and "public later" (YouTube `publishAt`) are blocked everywhere.** That covers Autopilot, the manual
*Prepare post* page, retries and older posts that were already scheduled. Anyone with an unlisted link could watch
the video, so unlisted is not a selected audience.

The rules are in one place, `clipfoundry/audience.py`. The scheduler, the approval check, the publisher, the manual
publish route and the upload jobs all call it, and its tests are in `tests/test_audience.py`.

## YouTube: private video plus invited viewers

1. ClipFoundry uploads the clip as **private** (never with `publishAt`) and reads the visibility back.
2. The post then shows **Awaiting viewer invitations**. The YouTube API has no call to invite viewers, so you do this
   yourself:
   - In [YouTube Studio](https://studio.youtube.com), open **Content**, then the video, then **Visibility → Private →
     Share privately**.
   - Add your viewers' email addresses. They need a Google account, and YouTube allows up to 50 people per video.
     Studio decides whether they get an email.
   - Back in ClipFoundry, press **I've invited my viewers**.
3. Only after step 2 does the post count as *viewers can watch*. A successful private upload alone means only you can
   see it ("Uploaded, only you").

If YouTube ever reports the video as public or unlisted (someone changed it in Studio), ClipFoundry stops all YouTube
uploads and asks you to check. That is *visibility drift*.

## TikTok: private account plus approved followers

TikTok's per-post choices are *Everyone*, *Followers*, *Friends* and *Only me*. With a **private account**, only
followers you approved can see *Followers* posts.

- **Before choosing Selected audience** you confirm two things in the app: your account is private, and you reviewed
  your followers (anyone you approved can see these posts).
- **Direct to Followers/Friends** needs a TikTok app that TikTok **audited** for Direct Post, and that option must be in
  the list TikTok returns for your account at that moment. ClipFoundry never picks *Everyone*.
- **Unaudited apps** can only post *Only me*. Then ClipFoundry builds a **manual posting package** instead:
  - the finished video file;
  - the caption and hashtags;
  - step-by-step instructions (*keep your account private, choose Followers, do not choose Everyone*).

  It appears in Queue under *Manual posting package*. After posting it on your phone, paste the post's link and press
  **I posted it**.
- Choosing *Friends* when the setting says *Followers* is allowed, because it is narrower. *Only me* under Selected
  audience is refused, because it would reach nobody.

## Approvals follow the audience

Each approval records the audience settings it was given under (`audience_policy`). If you change the audience, the
group, or the group version (for example after adding new testers), approved posts go back to *needs approval* with the
reason *who can see it changed after approval*.

## Older settings and posts

On first start after this update:

- A saved YouTube privacy of **private** becomes *Only me (staging)*.
- **public** or **unlisted** becomes *Keep on this PC*.
- Older planned posts that were public stay **blocked**; nothing widens.

The old setting is remembered (`audience_migrated_from`) so you can see what happened.

## Capability matrix

| Capability | Status |
| --- | --- |
| YouTube private upload, visibility read-back, drift halt | Implemented and tested against the fake API; real-account verification pending |
| YouTube invite viewers by API | Unsupported by the platform; manual step in Studio, confirmed by you |
| TikTok Followers/Friends Direct Post | Implemented and tested for audited apps; needs TikTok's audit (user action) |
| TikTok manual posting package | Implemented and tested |
| TikTok inbox draft | Existing path. ClipFoundry cannot set the audience there, so you choose it in the TikTok app |
| Test-audience analytics | See [BRAIN.md](BRAIN.md). Restricted TikTok posts have no public numbers, so you enter them yourself |
