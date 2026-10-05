import { Settings } from "../api";
import {
  Check, FieldCtx, NumInput, Seg, SecretField, SettingRow, SettingsPanel, Switch, TextInput,
} from "./settingsFields";

/**
 * Settings → Advanced, the Autopilot parts: details (time zone, limits, replacement, worker process), posting and
 * discovery and rights. The few choices most people need (daily target, posting hours, topics) are on Defaults,
 * automatic publishing on Accounts, and on/off on the Autopilot page. Saved with the Settings page's save bar.
 */
export function AutopilotSettings({ s, set, errors, saved }: {
  s: Settings; set: (p: Settings) => void; errors?: Record<string, string>; saved?: Settings;
}) {
  const c: FieldCtx = { s, set, errors, saved };
  const row = { errors };
  const topics = String(s.trend_topics || "");
  return (
    <>
      <SettingsPanel id="adv-ap" title="Autopilot details"
        intro={<>A post goes out only when it is approved: by you in Posts or, for YouTube, by the automatic-publishing
          permission on Settings, Accounts. <b>TikTok always needs your OK on each post.</b></>}>
        <SettingRow k="autopilot_local_test_mode" label="Local test mode"
          hint={"Automatically clip public videos for local testing, even without recorded reuse permission. Clips "
            + "stay on this PC and all uploads are off. Blocked or unavailable videos are still skipped"} {...row}>
          <Switch k="autopilot_local_test_mode" c={c} />
        </SettingRow>
        <SettingRow k="autopilot_timezone" label="Time zone" hint="Posting hours and planned times use this zone"
          {...row}>
          <TextInput k="autopilot_timezone" c={c} width={280} placeholder="America/Chicago" />
        </SettingRow>
        <SettingRow k="autopilot_keep_awake" label="Keep the PC awake"
          hint="Windows: the PC doesn't sleep while Autopilot is on (the screen still can)" {...row}>
          <Switch k="autopilot_keep_awake" c={c} />
        </SettingRow>
        <SettingRow k="autopilot_sources_per_day" label="Sources per day"
          hint="How many videos Autopilot takes on each day" {...row}>
          <NumInput k="autopilot_sources_per_day" c={c} />
        </SettingRow>
        <SettingRow k="autopilot_clips_per_source" label="Clips per source"
          hint="At most; a video with fewer strong moments gives fewer clips" {...row}>
          <NumInput k="autopilot_clips_per_source" c={c} />
        </SettingRow>
        <SettingRow k="autopilot_min_quality" label="Minimum clip quality"
          hint="Viral Potential (an estimate, 0 to 100) an Autopilot clip needs" {...row}>
          <NumInput k="autopilot_min_quality" c={c} />
        </SettingRow>
        <SettingRow label="Platforms" hint="Where Autopilot plans posts" group>
          <div className="row wrap" style={{ gap: 16 }}>
            <Check k="autopilot_youtube" c={c}>YouTube Shorts</Check>
            <Check k="autopilot_tiktok" c={c}>TikTok</Check>
          </div>
        </SettingRow>
        <SettingRow k="autopilot_auto_schedule" label="Automatic scheduling"
          hint="Plan posting times for new finished clips" {...row}>
          <Switch k="autopilot_auto_schedule" c={c} />
        </SettingRow>
        <SettingRow k="autopilot_dynamic_replacement" label="Replace weaker planned posts" group {...row}
          hint={"A clearly stronger new clip may take the time of the weakest future post. A time is swapped at "
            + `most once every ${s.autopilot_replacement_cooldown_hours ?? 24} hours, and the new post needs its `
            + "own OK"}>
          <Switch k="autopilot_dynamic_replacement" c={c} />
          <div className="inline-fields small">
            <span>At least</span>
            <NumInput k="autopilot_replacement_threshold" c={c} label="Replacement margin in percent" width={100} />
            <span>% better, at most once every</span>
            <NumInput k="autopilot_replacement_cooldown_hours" c={c} label="Replacement cooldown in hours"
              width={100} />
            <span>hours per time</span>
          </div>
          <Errors keys={["autopilot_replacement_threshold", "autopilot_replacement_cooldown_hours"]} errors={errors} />
        </SettingRow>
        <SettingRow k="autopilot_live_monitoring" label="Live monitoring"
          hint="Clip authorized live sources while they run" {...row}>
          <Switch k="autopilot_live_monitoring" c={c} />
        </SettingRow>
        <SettingRow k="autopilot_learning" label="Learning"
          hint="Use your real results to adjust times, topics and scores" {...row}>
          <Switch k="autopilot_learning" c={c} />
        </SettingRow>
        <SettingRow k="autopilot_process" label="Worker process"
          hint="Own process: a crash in a worker can't take the app down" group {...row}>
          <Seg k="autopilot_process" c={c}
            options={[{ value: "separate", label: "Own process" }, { value: "in_app", label: "Inside the app" }]} />
        </SettingRow>
        <SettingRow label="Largest source"
          hint={"Autopilot doesn't download bigger files or process longer videos (videos you add yourself have no "
            + "limit)"}
          group>
          <div className="inline-fields small">
            <NumInput k="autopilot_max_source_gb" c={c} label="Largest source in GB" step={0.5} width={100} />
            <span>GB</span>
            <NumInput k="autopilot_max_source_minutes" c={c} label="Longest source in minutes" width={100} />
            <span>minutes</span>
          </div>
          <Errors keys={["autopilot_max_source_gb", "autopilot_max_source_minutes"]} errors={errors} />
        </SettingRow>
      </SettingsPanel>

      <SettingsPanel id="adv-posting" title="Autopilot posting">
        <SettingRow k="autopilot_min_gap_minutes" label="Minimum gap"
          hint="Minutes between two posts on the same platform" {...row}>
          <NumInput k="autopilot_min_gap_minutes" c={c} />
        </SettingRow>
        <SettingRow label="Posts a day per platform" hint="Your limit; a lower limit reported by a platform wins" group>
          <div className="inline-fields small">
            <span>YouTube</span>
            <NumInput k="autopilot_youtube_daily_limit" c={c} label="YouTube posts a day" width={100} />
            <span>TikTok</span>
            <NumInput k="autopilot_tiktok_daily_limit" c={c} label="TikTok posts a day" width={100} />
          </div>
          <Errors keys={["autopilot_youtube_daily_limit", "autopilot_tiktok_daily_limit"]} errors={errors} />
        </SettingRow>
        <SettingRow k="autopilot_youtube_privacy" label="Suggested YouTube visibility"
          hint="You confirm it for every post when approving" group {...row}>
          <Seg k="autopilot_youtube_privacy" c={c}
            options={[{ value: "public", label: "Public" }, { value: "unlisted", label: "Unlisted" },
              { value: "private", label: "Private" }]} />
        </SettingRow>
        <SettingRow k="autopilot_upload_lead_minutes" label="Upload YouTube posts early" {...row}
          hint="Minutes before the planned time. YouTube publishes at the planned time, even if this PC is off by then">
          <NumInput k="autopilot_upload_lead_minutes" c={c} />
        </SettingRow>
        <SettingRow k="autopilot_auto_publish" label="Publish approved posts at their time" {...row}
          hint="Off: approved posts wait at their time until you press Publish now in Posts">
          <Switch k="autopilot_auto_publish" c={c} />
        </SettingRow>
        <SettingRow k="autopilot_allow_republish" label="Allow republishing"
          hint="Post a clip (or the same moment) again on a platform" {...row}>
          <Switch k="autopilot_allow_republish" c={c} />
        </SettingRow>
        <SettingRow k="youtube_category_id" label="YouTube category"
          hint="YouTube's category number for uploads (22 = People & Blogs)" {...row}>
          <TextInput k="youtube_category_id" c={c} width={120} />
        </SettingRow>
      </SettingsPanel>

      <SettingsPanel id="adv-disc" title="Discovery and rights"
        intro={"Discovery is not permission to reuse or post a video. Local test mode can make local clips from public "
          + "videos without recorded reuse permission. Otherwise, uncovered videos are skipped. Blocked videos are "
          + "always skipped and listed in Activity."}>
        <SettingRow label="Region and language" hint="Two-letter country and language codes (US and en by default)"
          group>
          <div className="inline-fields small">
            <TextInput k="trend_region" c={c} label="Region" width={90} />
            <TextInput k="trend_language" c={c} label="Language for discovery" width={90} />
          </div>
          <Errors keys={["trend_region"]} errors={errors} />
        </SettingRow>
        <SettingRow label="Topics" hint="Edited on Settings, Defaults" group>
          <span className="small muted">
            {topics.slice(0, 160) || "None"}{topics.length > 160 ? "…" : ""}{" "}
            <a className="textlink" href="#/settings/defaults">Change</a>
          </span>
        </SettingRow>
        <SettingRow k="trend_poll_minutes" label="Check trends every"
          hint="Minutes (every 3 hours by default); slowed down automatically near the quota share" {...row}>
          <NumInput k="trend_poll_minutes" c={c} />
        </SettingRow>
        <SettingRow k="trend_max_age_hours" label="Consider videos up to" hint="Hours old" {...row}>
          <NumInput k="trend_max_age_hours" c={c} />
        </SettingRow>
        <SettingRow k="youtube_api_key" label="YouTube Data API key"
          hint="Optional: discovery without a connected account (same project quota)" {...row}>
          <SecretField k="youtube_api_key" c={c} removable placeholder="AIza…" />
        </SettingRow>
        <SettingRow k="youtube_derived_metrics_approved" label="Google approved derived metrics" {...row}
          hint={"Only if Google accepted your project under YouTube's additional policies for derived metrics and "
            + "data storage"}>
          <Switch k="youtube_derived_metrics_approved" c={c} />
          <span className="tiny muted">
            YouTube's Developer Policies don't allow metrics derived from YouTube API data (view velocity, engagement
            rates, totals, learning from your YouTube results) without Google's approval, and YouTube data must be
            refreshed or deleted within 30 days. While this is off, YouTube results keep YouTube's own order and are
            shown exactly as reported. With it on, the statistics of your own videos are also kept longer while your
            channel stays connected; public data about other videos is still deleted after 30 days.
          </span>
        </SettingRow>
        <SettingRow k="tavily_api_key" label="Web search (Tavily) key" {...row}
          hint={"Optional: finds public TikTok links for your topics and the long YouTube videos behind popular "
            + "clips. It gives titles and links, not TikTok statistics"}>
          <SecretField k="tavily_api_key" c={c} removable placeholder="tvly-…" />
        </SettingRow>
        <SettingRow k="tavily_free_credits" label="Web search credits included"
          hint="Per month in your Tavily plan (the free plan: 1,000; one search = 1 credit)" {...row}>
          <NumInput k="tavily_free_credits" c={c} />
        </SettingRow>
        <SettingRow k="discovery_monthly_budget_usd" label="Monthly cost limit"
          hint="US dollars for paid searches beyond the included credits. 0 = never spend money" {...row}>
          <div className="inline-fields small">
            <NumInput k="discovery_monthly_budget_usd" c={c} step={1} />
            <span>US dollars a month</span>
          </div>
        </SettingRow>
        <SettingRow k="library_discovery" label="Free-license library"
          hint={"Search Wikimedia Commons for videos their authors released under a free license (public domain, "
            + "CC0, CC BY)"}
          {...row}>
          <Switch k="library_discovery" c={c} />
        </SettingRow>
        <SettingRow label="Use automatically" group
          hint={"Which kinds of permission let Autopilot clip and post without asking. Record agreements with "
            + "creators in Autopilot, Sources"}>
          <div className="stack" style={{ gap: 0 }}>
            <Check k="rights_auto_licensed" c={c}>Licensed sources</Check>
            <Check k="rights_auto_allowlisted" c={c}>
              Allowlisted sources (creator agreements, clipping programs you joined)
            </Check>
            <Check k="rights_auto_creative_commons" c={c}>
              Creative Commons (CC BY, with a credit line; share-alike, non-commercial and no-derivatives licenses are
              never used)
            </Check>
            <Check k="rights_auto_public_domain" c={c}>Public domain and CC0, as the library reports it</Check>
          </div>
        </SettingRow>
        <SettingRow k="autopilot_commercial_use" label="My posts are commercial" {...row}
          hint="Monetized, sponsored or promoting a business. On: agreements that exclude commercial use are not used">
          <Switch k="autopilot_commercial_use" c={c} />
        </SettingRow>
        <SettingRow k="rights_ask_per_video" label="Ask me about strong videos nothing covers" {...row}
          hint={"Off (recommended): they're skipped and listed in Activity. On: up to 3 questions at a time, only "
            + "when today's plan is short"}>
          <Switch k="rights_ask_per_video" c={c} />
        </SettingRow>
        <SettingRow k="rights_allow_remote_download" label="Download authorized platform sources" {...row}
          hint="With the address importer, for sources that pass the permission check">
          <Switch k="rights_allow_remote_download" c={c} />
          <span className="tiny muted">
            YouTube's Terms only allow downloads through YouTube's own features, or with permission from YouTube and
            the rights holders. For your own videos, the clean path is YouTube Studio, Download, or your original
            recordings in your videos folder. Turn this on only if you have that permission.
          </span>
        </SettingRow>
        <SettingRow label="Daily quota of your project" group hint="Google Cloud console, YouTube Data API v3, Quotas">
          <div className="inline-fields small">
            <span>Units</span><NumInput k="youtube_quota_default" c={c} label="Quota units a day" width={130} />
            <span>Uploads</span><NumInput k="youtube_quota_uploads" c={c} label="Quota uploads a day" width={100} />
            <span>Searches</span><NumInput k="youtube_quota_search" c={c} label="Quota searches a day" width={100} />
          </div>
          <Errors keys={["youtube_quota_default", "youtube_quota_uploads", "youtube_quota_search"]} errors={errors} />
        </SettingRow>
        <SettingRow label="Discovery may use" group
          hint="Share of each daily allowance; the rest is kept for publishing, statistics and account checks">
          <div className="inline-fields small">
            <NumInput k="youtube_discovery_share" c={c} label="Discovery share of quota units in percent"
              width={90} />
            <span>% of units</span>
            <NumInput k="youtube_search_discovery_share" c={c} label="Discovery share of searches in percent"
              width={90} />
            <span>% of searches</span>
          </div>
          <Errors keys={["youtube_discovery_share", "youtube_search_discovery_share"]} errors={errors} />
        </SettingRow>
        <p className="tiny faint">
          Not available and never scraped: Google Trends (the official API is an application-only alpha) and a TikTok
          trend API (TikTok has none for general developers). TikTok numbers are never guessed: without an official
          source they are shown as unknown.
        </p>
      </SettingsPanel>
    </>
  );
}

/** Errors of the boxes in a row that holds several (each box links to its own message). */
export function Errors({ keys, errors }: { keys: string[]; errors?: Record<string, string> }) {
  return (
    <>
      {keys.filter((k) => errors?.[k]).map((k) => (
        <span key={k} className="error-text" id={`set-${k}-err`}>{errors![k]}</span>
      ))}
    </>
  );
}
