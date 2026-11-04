import { Logo } from "../components/ui";
import { signInUrl } from "../session";

/** Cloud sign-in. Nothing private is requested before the server accepts the session. */
export default function SignIn({ ended }: { ended?: boolean }) {
  const failed = new URLSearchParams(window.location.search).get("signin") === "failed";
  return (
    <main className="signin">
      <div className="card">
        <Logo size={56} />
        <h1>ClipForge</h1>
        <p className="muted">{ended ? "Your session ended. Sign in again to continue where you were." :
          "Sign in to your private studio."}</p>
        {failed && <p className="error-text">Sign-in did not finish. Try again.</p>}
        <a className="btn btn-primary btn-large" href={signInUrl()}>Continue with Google</a>
        <p className="small muted">Only the owner's account can open this studio.</p>
      </div>
    </main>
  );
}
