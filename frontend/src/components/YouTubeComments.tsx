/** The upload API has no switch to enable YouTube comments; never promise that an audience answer enables them. */
export function YouTubeComments({ privacy, kids }: { privacy?: string; kids: boolean | null }) {
  return <p className="small muted">
    {kids === true ? "Comments will be off: YouTube disables them on videos made for kids. "
      : privacy === "private" ? "Comments will be off: YouTube does not allow them on Private videos. "
        : "YouTube disables comments on videos made for kids and on Private videos. "}
    Made for kids means intended for children; being suitable for all ages alone does not decide this.
    {kids !== true && privacy !== "private" ? " Channel defaults and YouTube restrictions can still turn comments "
      + "off; check YouTube Studio." : ""}
  </p>;
}

export function YouTubeCommentsResult({ info }: { info?: Record<string, any> }) {
  const note = info?.youtube_audience?.comments_note;
  return typeof note === "string" && note ? <p className="small muted"><b>Comments:</b> {note}</p> : null;
}
