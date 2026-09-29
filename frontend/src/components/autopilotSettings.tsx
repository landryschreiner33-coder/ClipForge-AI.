import { ReactNode } from "react";
import { Settings } from "../api";
import { Segmented, Toggle } from "./ui";

function Row({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div className="opt-row">
      <div className="lbl">{label}{hint && <small>{hint}</small>}</div>
      <div>{children}</div>
    </div>
  );
}

const num = (v: string) => (v === "" ? 0 : +v);

/** Every Autopilot control except the ones on Settings → General (on/off, daily target, automatic publishing).
 * Saved with the Settings page's Save button. */
export function AutopilotSettings({ s, set }: { s: Settings; set: (p: Settings) => void }) {
  const tog = (key: string) => <Toggle on={!!s[key]} onChange={(v) => set({ [key]: v })} />;
  const n = (key: string, props: Record<string, number> = {}) => (
    <input type="number" value={s[key]} {...props} onChange={(e) => set({ [key]: num(e.target.value) })} style={{ maxWidth: 140 }} />
  );
  return (
    <>
      <div className="card" id="autopilot">
        <h3>Autopilot details</h3>
        <div className="notice small">
          <div>
            Autopilot finds, clips, packages and schedules on its own. A post goes out only when it is approved: by you in the Publish Center,
            or, for YouTube, by the automatic-publishing permission you can give on Settings → General. <b>TikTok always needs your OK on each
            post</b> (its rules require your consent and a preview before each upload). Approved posts are published at their time.
          </div>
        </div>
        <Row label="Sources per day">{n("autopilot_sources_per_day", { min: 1, max: 30 })}</Row>
        <Row label="Clips per source" hint="At most; a source with fewer strong moments gives fewer clips">{n("autopilot_clips_per_source", { min: 1, max: 10 })}</Row>
        <Row label="Minimum clip quality" hint="Clip Score needed for Autopilot clips">
          <div className="row"><input type="range" min={0} max={95} step={5} value={s.autopilot_min_quality} onChange={(e) => set({ autopilot_min_quality: +e.target.value })} /><b style={{ width: 30 }}>{s.autopilot_min_quality}</b></div>
        </Row>
        <Row label="Platforms"><div className="row wrap" style={{ gap: 18 }}>
          <label className="row small">{tog("autopilot_youtube")} YouTube Shorts</label>
          <label className="row small">{tog("autopilot_tiktok")} TikTok</label>
        </div></Row>
        <Row label="Automatic scheduling" hint="Plan posting times for new packaged clips">{tog("autopilot_auto_schedule")}</Row>
        <Row label="Dynamic trend replacement" hint="A clearly stronger new opportunity takes the slot of the weakest future post">
          <div className="row">{tog("autopilot_dynamic_replacement")}<span className="small muted">at least</span>{n("autopilot_replacement_threshold", { min: 0, max: 500 })}<span className="small muted">% better</span></div>
        </Row>
        <Row label="Live monitoring" hint="Clip authorized live sources while they run">{tog("autopilot_live_monitoring")}</Row>
        <Row label="Learning" hint="Use your real results to adjust times, topics and scores">{tog("autopilot_learning")}</Row>
        <Row label="Time zone"><input type="text" value={s.autopilot_timezone} onChange={(e) => set({ autopilot_timezone: e.target.value })} style={{ maxWidth: 240 }} /></Row>
        <Row label="Active hours" hint="Posts only between these local hours">
          <div className="row">{n("autopilot_active_start", { min: 0, max: 23 })}<span className="muted">to</span>{n("autopilot_active_end", { min: 1, max: 24 })}</div>
        </Row>
        <Row label="Minimum gap" hint="Minutes between two posts on the same platform">{n("autopilot_min_gap_minutes", { min: 0, max: 1440 })}</Row>
        <Row label="Posts per day per platform" hint="Your limit; a lower limit reported by a platform wins">
          <div className="row"><span className="small muted">YouTube</span>{n("autopilot_youtube_daily_limit", { min: 0, max: 100 })}<span className="small muted">TikTok</span>{n("autopilot_tiktok_daily_limit", { min: 0, max: 100 })}</div>
        </Row>
        <Row label="Suggested YouTube visibility" hint="You confirm it for every post when approving">
          <Segmented value={s.autopilot_youtube_privacy} onChange={(v) => set({ autopilot_youtube_privacy: v })}
            options={[{ value: "public", label: "Public" }, { value: "unlisted", label: "Unlisted" }, { value: "private", label: "Private" }]} />
        </Row>
        <Row label="Upload YouTube posts early" hint="Minutes before the planned time; YouTube publishes at the planned time, even if this PC is off by then">{n("autopilot_upload_lead_minutes", { min: 5, max: 720 })}</Row>
        <Row label="Publish approved posts at their time" hint="Off: approved posts wait for Publish now in the Publish Center">{tog("autopilot_auto_publish")}</Row>
        <Row label="Allow republishing" hint="Post a clip (or the same moment) again on a platform">{tog("autopilot_allow_republish")}</Row>
        <Row label="Worker process" hint="Own process: a crash in a worker cannot take the app down">
          <Segmented value={s.autopilot_process} onChange={(v) => set({ autopilot_process: v })}
            options={[{ value: "separate", label: "Own process" }, { value: "in_app", label: "Inside the app" }]} />
        </Row>
      </div>

      <div className="card">
        <h3>Discovery</h3>
        <Row label="Region and language" hint="US/English by default">
          <div className="row"><input type="text" value={s.trend_region} onChange={(e) => set({ trend_region: e.target.value })} style={{ maxWidth: 80 }} />
            <input type="text" value={s.trend_language} onChange={(e) => set({ trend_language: e.target.value })} style={{ maxWidth: 80 }} /></div>
        </Row>
        <Row label="Topics" hint="Broad on purpose; searched a few at a time (comma-separated)">
          <textarea rows={2} value={s.trend_topics} onChange={(e) => set({ trend_topics: e.target.value })} />
        </Row>
        <Row label="Check trends every" hint="Minutes (every 3 hours by default); slowed down automatically near the quota share">{n("trend_poll_minutes", { min: 15, max: 1440 })}</Row>
        <Row label="Consider videos up to" hint="Hours old">{n("trend_max_age_hours", { min: 6, max: 720 })}</Row>
        <Row label="YouTube Data API key" hint="Optional: discovery without a connected account (same project quota)">
          <input type="password" value={s.youtube_api_key} placeholder="AIza..." onChange={(e) => set({ youtube_api_key: e.target.value })} />
        </Row>
        <Row label="Google approved derived metrics" hint="Only if Google accepted your project under YouTube's additional policies for derived metrics and data storage">
          <div>
            {tog("youtube_derived_metrics_approved")}
            <div className="small muted mt-s">
              YouTube's Developer Policies do not allow metrics derived from YouTube API data (view velocity, engagement rates, totals,
              learning from your YouTube results) without Google's approval, and YouTube data must be refreshed or deleted within 30 days.
              While this is off, YouTube results keep YouTube's own order and are shown exactly as reported. With it on, the
              statistics of your own videos are also kept longer while your channel stays connected; public data about other
              videos is still deleted after 30 days.
            </div>
          </div>
        </Row>
        <Row label="Web search (Tavily) API key" hint="Optional: finds public TikTok links for your topics and the long YouTube videos behind popular clips. Web search gives titles and links, not TikTok statistics">
          <input type="password" value={s.tavily_api_key} placeholder="tvly-..." onChange={(e) => set({ tavily_api_key: e.target.value })} />
        </Row>
        <Row label="Web search credits included" hint="Per month in your Tavily plan (the free plan: 1,000; one search = 1 credit)">{n("tavily_free_credits", { min: 0, max: 1000000 })}</Row>
        <Row label="Monthly cost limit" hint="US dollars you allow for paid searches beyond the included credits. 0 = never spend money">
          <div className="row">{n("discovery_monthly_budget_usd", { min: 0, max: 1000, step: 1 })}<span className="small muted">USD a month</span></div>
        </Row>
        <Row label="Free-license library" hint="Search Wikimedia Commons for videos their authors released under a free license (public domain, CC0, CC BY)">{tog("library_discovery")}</Row>
        <div className="small muted">Not available and never scraped: Google Trends (the official API is an application-gated alpha) and a TikTok trend API (TikTok has none for general developers). TikTok numbers are never guessed: without an official source they are shown as unknown.</div>
      </div>

      <div className="card">
        <h3>Rights</h3>
        <div className="notice warn small">
          <div>Discovery is not authorization. Owned sources are always allowed; choose which other kinds of coverage may be clipped and published without asking. Blocked and uncovered videos never are: Autopilot skips them and keeps looking. Record agreements with creators under Autopilot → Advanced → Sources & rights.</div>
        </div>
        <Row label="Licensed sources">{tog("rights_auto_licensed")}</Row>
        <Row label="Allowlisted sources" hint="Creators you have an agreement with, or whose clipping program you joined">{tog("rights_auto_allowlisted")}</Row>
        <Row label="Creative Commons (CC BY) sources" hint="A credit line is added to the description. Share-alike, non-commercial and no-derivatives licenses are never used automatically">{tog("rights_auto_creative_commons")}</Row>
        <Row label="Public domain sources" hint="Public domain or CC0, as the library reports it">{tog("rights_auto_public_domain")}</Row>
        <Row label="My posts are commercial" hint="Monetized, sponsored or promoting a business. On: agreements that exclude commercial use are not used">{tog("autopilot_commercial_use")}</Row>
        <Row label="Ask me about strong videos nothing covers" hint="Off (recommended): they are skipped and listed in the activity log. On: up to 3 questions at a time, only when today's plan is short">{tog("rights_ask_per_video")}</Row>
        <Row label="Download authorized platform sources" hint="With the URL importer, for sources that pass the rights check">
          <div>
            {tog("rights_allow_remote_download")}
            <div className="small muted mt-s">
              YouTube's Terms only allow downloads through YouTube's own features, or with permission from YouTube and the rights holders.
              For your own videos, the clean path is YouTube Studio → Download, or your original recordings in a watch folder. Turn this on
              only if you have that permission.
            </div>
          </div>
        </Row>
      </div>

      <div className="card">
        <h3>YouTube quota and GPU</h3>
        <Row label="Daily quota of your project" hint="Google Cloud console → YouTube Data API v3 → Quotas">
          <div className="row wrap"><span className="small muted">units</span>{n("youtube_quota_default")}<span className="small muted">uploads</span>{n("youtube_quota_uploads")}<span className="small muted">searches</span>{n("youtube_quota_search")}</div>
        </Row>
        <Row label="Discovery may use" hint="Share of each budget; the rest is kept for publishing, statistics and account checks">
          <div className="row wrap">{n("youtube_discovery_share", { min: 0, max: 90 })}<span className="small muted">% of units</span>{n("youtube_search_discovery_share", { min: 0, max: 100 })}<span className="small muted">% of searches</span></div>
        </Row>
        <Row label="Free GPU memory needed" hint="Autopilot waits for this much free VRAM before transcribing (MB)">{n("gpu_min_free_vram_mb", { min: 0, max: 48000 })}</Row>
        <Row label="Wait for the GPU up to" hint="Minutes, then the job waits and tries later">{n("gpu_wait_minutes", { min: 1, max: 720 })}</Row>
        <Row label="Largest source" hint="Autopilot does not download bigger files or process longer videos (manual projects have no limit)">
          <div className="row">{n("autopilot_max_source_gb", { min: 0.5, max: 200, step: 0.5 })}<span className="small muted">GB</span>{n("autopilot_max_source_minutes", { min: 5, max: 1440 })}<span className="small muted">minutes</span></div>
        </Row>
        <Row label="Allow CPU transcription" hint="Off: if the GPU fails, Autopilot pauses transcription and tells you why (manual projects always fall back, visibly). On: it continues on the CPU, much slower">{tog("autopilot_allow_cpu_fallback")}</Row>
      </div>
    </>
  );
}
