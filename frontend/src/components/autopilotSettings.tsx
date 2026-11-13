import { Settings } from "../api";
import {
  Check, FieldCtx, NumInput, Seg, SettingRow, SettingsPanel, Switch, TextInput,
} from "./settingsFields";

/**
 * Settings → Advanced, the Autopilot parts: details (time zone, limits, replacement, worker process), posting,
 * rights and YouTube data rules. The few choices most people need (daily target, posting hours) are on Defaults,
 * automatic publishing on Accounts, and on/off on the Autopilot page. Saved with the Settings page's save bar.
 */
export function AutopilotSettings({ s, set, errors, saved }: {
  s: Settings; set: (p: Settings) => void; errors?: Record<string, string>; saved?: Settings;
}) {
  const c: FieldCtx = { s, set, errors, saved };
  const row = { errors };
  return (
    <>
      <SettingsPanel id="adv-ap" title="Autopilot details"
        intro={<>Add videos in Missions to make Brain-guided clips. “Make & upload clips” authorizes passing clips
          from just that submitted video. Other posts keep their own review and publishing requirements.</>}>
        <SettingRow label="Video intake" hint="ClipForge works on the videos and links you add" group>
          <span className="small muted">Only videos you add (a file or a link). Automatic searching for videos to
            clip was removed; earlier clips, posts and approvals are unchanged.</span>
        </SettingRow>
        <SettingRow k="autopilot_review_before_publish" label="Prepare & schedule for review"
          hint={"On: ordinary posts wait for your review and approval; standing automatic-publishing permission "
            + "is suspended. A new video you explicitly submit with Make & upload uses only its own authorization."} {...row}>
          <Switch k="autopilot_review_before_publish" c={c} />
          <a className="textlink small" href="#/publishing/review">Review prepared posts</a>
          <span className="tiny muted">Turning this off lets eligible YouTube posts use an existing
            automatic-publishing permission again. Clips without recorded coverage still need your review.</span>
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
          hint="0 means no daily cap; the unfinished work queue stays small" {...row}>
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
          hint="Bounded file-size and duration checks for the videos you add."
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
          hint="30 minutes by default, including after a restart. 0 disables spacing; platform waits still apply" {...row}>
          <NumInput k="autopilot_min_gap_minutes" c={c} />
        </SettingRow>
        <SettingRow label="Posts a day per platform"
          hint="0 means no app daily cap; platform limits and API allowances still apply" group>
          <div className="inline-fields small">
            <span>YouTube</span>
            <NumInput k="autopilot_youtube_daily_limit" c={c} label="YouTube posts a day" width={100} />
            <span>TikTok</span>
            <NumInput k="autopilot_tiktok_daily_limit" c={c} label="TikTok posts a day" width={100} />
          </div>
          <Errors keys={["autopilot_youtube_daily_limit", "autopilot_tiktok_daily_limit"]} errors={errors} />
        </SettingRow>
        <SettingRow k="autopilot_upload_lead_minutes" label="Upload YouTube posts early" {...row}
          hint="Private uploads only: minutes before the planned time. Public posts upload at their planned time">
          <NumInput k="autopilot_upload_lead_minutes" c={c} />
        </SettingRow>
        <SettingRow k="autopilot_auto_publish" label="Publish approved posts at their time" {...row}
          hint="Only after your approval. Off: approved posts wait until you press Publish now in Queue">
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

      <SettingsPanel id="adv-disc" title="Rights and YouTube data"
        intro="How recorded permissions are used for the videos you add, and YouTube's data rules. No search key is needed for videos you add.">
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
        <SettingRow label="Recorded reuse coverage" group
          hint={"Which recorded permissions are accepted. Review mode still waits for your approval on every post. "
            + "Record creator agreements under Missions, Permissions & sources"}>
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
