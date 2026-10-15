import { useId } from "react";

export type ReuseKind = "" | "owned" | "creator_permission" | "licensed" | "public_domain" | "custom";
export type ReuseOption = { value: Exclude<ReuseKind, "">; label: string; basis?: string };
export const REUSE_OPTIONS: ReuseOption[] = [
  { value: "owned", label: "My original content" },
  { value: "creator_permission", label: "Creator permission" },
  { value: "licensed", label: "License allows this use" },
  { value: "public_domain", label: "Public domain" },
  { value: "custom", label: "Other permission" },
];

/** Choosing a reason records an owner assertion, never a verified license or a default claim. */
export function ReuseBasis({ kind, basis, onChange, options = REUSE_OPTIONS, multiple = false, disabled = false }: {
  kind: ReuseKind; basis: string; onChange: (kind: ReuseKind, basis: string) => void;
  options?: ReuseOption[]; multiple?: boolean; disabled?: boolean;
}) {
  const id = useId();
  return (
    <fieldset className="reuse-basis" disabled={disabled}>
      <legend className="small strong">Why I can reuse {multiple ? "these clips" : "it"}</legend>
      <p className="tiny muted">Choose the reason you checked. {multiple
        ? "It must cover every selected clip that needs your reuse confirmation, including music and other material."
        : "Include music and any other material in the clip."} This records your review, not a verified license.</p>
      <div className="reuse-choices">
        {options.map((option) => <label key={option.value} className={`reuse-option ${kind === option.value ? "selected" : ""}`}>
          <input type="radio" name={`reuse-kind-${id}`} value={option.value} checked={kind === option.value}
            onChange={() => onChange(option.value, basis)} />
          <span>{option.label}</span>
        </label>)}
      </div>
      {kind === "creator_permission" && <p className="tiny muted">The creator gave you permission for this use,
        including the material in the {multiple ? "clips" : "clip"}.</p>}
      {kind === "licensed" && <p className="tiny muted">You checked that the license permits this use,
        including any music, and that required credit is present.</p>}
      {kind === "custom" && <label className="stack small" htmlFor={`reuse-basis-${id}`}>
        <span className="strong">Permission details</span>
        <textarea id={`reuse-basis-${id}`} className="input" rows={3} maxLength={4000} value={basis}
          onChange={(e) => onChange(kind, e.target.value)} placeholder="Record the permission or other basis you checked." />
      </label>}
    </fieldset>
  );
}
