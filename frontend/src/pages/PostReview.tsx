import { PageHead } from "../components/ui";

// Placeholder while the page is built (replaced in this change).
export default function PostReview({ id }: { id?: string }) {
  return <div className="page"><PageHead title="Post review" sub={id} /></div>;
}
