import { useId } from "react";

/** Suggested topics for what Autopilot looks for online. Any other topic can be typed. */
export const TOPIC_CHOICES = [
  "podcasts", "interviews", "comedy", "sports", "gaming", "science", "business", "education", "news", "technology",
];
export const DEFAULT_TOPICS = "podcasts, interviews, comedy";
export const splitTopics = (t: string) => t.split(",").map((x) => x.trim()).filter(Boolean);

/** The one topic choice: a suggested list you can change by clicking or typing. */
export function TopicChoice({ topics, setTopics, allowEmpty = false }: {
  topics: string; setTopics: (t: string) => void; allowEmpty?: boolean;
}) {
  const id = useId();
  const list = splitTopics(topics);
  const has = (t: string) => list.some((x) => x.toLowerCase() === t);
  const flip = (t: string) => setTopics((has(t) ? list.filter((x) => x.toLowerCase() !== t) : [...list, t]).join(", "));
  return (
    <div className="field">
      <span className="label" id={`${id}-l`}>What should it look for online?</span>
      <span className="hint" id={`${id}-h`}>
        {allowEmpty ? "Choose topics, or leave this empty to look for videos on any topic."
          : "A suggestion is filled in. Click a topic to add or remove it, or type your own."}
      </span>
      <div className="chips" role="group" aria-labelledby={`${id}-l`}>
        {TOPIC_CHOICES.map((t) => (
          <button key={t} type="button" className="chip" aria-pressed={has(t)} onClick={() => flip(t)}>{t}</button>
        ))}
      </div>
      <input type="text" aria-label="Topics" aria-describedby={`${id}-h`} value={topics}
        onChange={(e) => setTopics(e.target.value)} placeholder={allowEmpty ? "Any topic" : DEFAULT_TOPICS} />
    </div>
  );
}
