import { PageHead } from "../components/ui";

// Placeholder while the page is built (replaced in this change).
export default function Setup({ step }: { step?: string }) {
  return <div className="page"><PageHead title="Set up ClipFoundry" sub={step} /></div>;
}
