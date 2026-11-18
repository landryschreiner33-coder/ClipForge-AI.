import { useEffect, useId, useRef, useState } from "react";
import { Connection, studio } from "../studio";

export type ChannelPlatform = "youtube" | "tiktok";

const GROUP_TITLE: Record<ChannelPlatform, string> = { youtube: "YouTube channels", tiktok: "TikTok accounts" };
const PLATFORM_WORD: Record<ChannelPlatform, string> = { youtube: "YouTube", tiktok: "TikTok" };

/** The name the owner knows an account by: their own nickname, else the platform's name for it. */
export const accountName = (c: Pick<Connection, "nickname" | "display_name" | "account_id">) =>
  c.nickname || c.display_name || c.account_id;

/** An account that can take a new post now (connected, signed in). A server without the flag reports it in health. */
export const isPostable = (c: Connection) => c.postable ?? c.health?.state === "ok";

/** "A", "A and B", "A, B and C": names in a sentence. */
export const nameList = (names: string[]) =>
  names.length <= 1 ? names[0] || "" : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;

/**
 * The accounts ticked before the owner changes anything: postable accounts marked "Tick for new posts"; a platform
 * with none marked ticks its default account (when it can take a post).
 */
export function defaultTicks(rows: Connection[], platforms: ChannelPlatform[]): string[] {
  return platforms.flatMap((platform) => {
    const usable = rows.filter((r) => r.platform === platform && isPostable(r));
    const marked = usable.filter((r) => r.post_by_default ?? r.is_default);
    return (marked.length ? marked : usable.filter((r) => r.is_default)).map((r) => r.id);
  });
}

type Props = {
  platforms: ChannelPlatform[];
  value: string[];
  onChange: (ids: string[], accounts: Connection[]) => void;
  /** The accounts to offer; loaded from Accounts when left out. */
  rows?: Connection[];
  /** "defaults": with nothing ticked yet, tick the defaults once the accounts are known. "none": the caller decides. */
  preselect?: "defaults" | "none";
  idPrefix?: string;
  legend?: string;
};

/**
 * Which accounts a post goes to: every connected YouTube channel and TikTok account by name and picture, grouped by
 * platform, with All for a platform that has two or more. An account that can't take a post now is shown but can't be
 * ticked, with the reason. Choosing never changes the account itself.
 */
export function ChannelPicker(props: Props) {
  const { platforms, value, onChange, rows: given, preselect = "defaults", idPrefix, legend } = props;
  const [loaded, setLoaded] = useState<Connection[] | null>(null);
  const autoId = useId();
  const id = idPrefix || autoId;
  const rows = given ?? loaded;
  useEffect(() => {
    if (given) return;
    let alive = true;
    studio.connections().then((r) => alive && setLoaded(r.connections)).catch(() => alive && setLoaded([]));
    return () => {
      alive = false;
    };
  }, [given]);

  const mine = (rows || []).filter((r) => platforms.includes(r.platform));
  const choose = (ids: string[]) => onChange(ids, mine.filter((r) => ids.includes(r.id)));

  // Once the accounts are known: tick the defaults (only the first time), and never keep an account that can't post.
  const started = useRef(false);
  const rowsKey = mine.map((r) => `${r.id}:${isPostable(r) ? 1 : 0}`).join("|");
  useEffect(() => {
    if (!rows) return;
    if (!mine.length) {
      if (value.length) choose([]);
      return;
    }
    const ok = new Set(mine.filter(isPostable).map((r) => r.id));
    if (!started.current) {
      started.current = true;
      if (preselect === "defaults" && !value.length) {
        const ticks = defaultTicks(mine, platforms);
        if (ticks.length) choose(ticks);
        return;
      }
    }
    const kept = value.filter((v) => ok.has(v));
    if (kept.length !== value.length) choose(kept);
  }, [rows === null, rowsKey]); // eslint-disable-line react-hooks/exhaustive-deps

  if (rows === null) return <p className="muted small">Loading accounts…</p>;
  if (!mine.length) {
    const what = platforms.length === 1 ? PLATFORM_WORD[platforms[0]] : "YouTube or TikTok";
    return <p className="small">No account connected yet. <a className="textlink" href="#/accounts">Connect {what} in
      Accounts</a>.</p>;
  }
  return (
    <fieldset className="channel-picker">
      <legend className="sr-only">{legend || "Accounts to post to"}</legend>
      {platforms.map((platform) => {
        const list = mine.filter((r) => r.platform === platform);
        if (!list.length) return null;
        return <ChannelGroup key={platform} id={`${id}-${platform}`} platform={platform} list={list} value={value}
          onPick={choose} />;
      })}
    </fieldset>
  );
}

function ChannelGroup({ id, platform, list, value, onPick }: {
  id: string; platform: ChannelPlatform; list: Connection[]; value: string[]; onPick: (ids: string[]) => void;
}) {
  const usable = list.filter(isPostable);
  const on = usable.filter((r) => value.includes(r.id));
  const all = usable.length > 0 && on.length === usable.length;
  const some = on.length > 0 && !all;
  const allBox = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (allBox.current) allBox.current.indeterminate = some;
  }, [some]);
  const others = value.filter((v) => !list.some((r) => r.id === v));
  const toggleAll = () => onPick(all ? others : [...others, ...usable.map((r) => r.id)]);
  return (
    <div className="channel-group" role="group" aria-labelledby={`${id}-title`}>
      <div className="channel-group-head">
        <span className="small strong" id={`${id}-title`}>{GROUP_TITLE[platform]}</span>
        {usable.length >= 2 && (
          <label className="channel-all">
            <input ref={allBox} type="checkbox" checked={all} onChange={toggleAll} />
            <span>All ({usable.length})<span className="sr-only"> {GROUP_TITLE[platform]}</span></span>
          </label>
        )}
      </div>
      <div className="dest-list">
        {list.map((r) => {
          const ok = isPostable(r);
          const checked = ok && value.includes(r.id);
          const name = accountName(r);
          const why = `${id}-${r.id}-why`;
          return (
            <label key={r.id} className={`dest${ok ? "" : " off"}`}>
              <input type="checkbox" checked={checked} disabled={!ok} aria-describedby={ok ? undefined : why}
                onChange={() => onPick(checked ? value.filter((v) => v !== r.id) : [...value, r.id])} />
              {r.avatar ? <img src={r.avatar} alt="" className="avatar" referrerPolicy="no-referrer"
                onError={(e) => { e.currentTarget.removeAttribute("src"); }} />
                : <span className="avatar" aria-hidden="true" />}
              <span className="break">
                <span className="who-name">{name}</span>
                {r.is_default && <span className="small muted"> · default</span>}
                {!ok && <span className="block small error-text" id={why}>
                  {r.health?.text || "Can't post right now."}</span>}
              </span>
            </label>
          );
        })}
      </div>
    </div>
  );
}
