import { PageHead } from "../components/ui";

// Placeholder while the page is built (replaced in this change).
export default function Posts({ view }: { view?: string }) {
  return <div className="page"><PageHead title="Posts" sub={view} /></div>;
}
