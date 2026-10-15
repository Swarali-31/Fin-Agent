import { AlertCircle, AlertTriangle, Inbox, LoaderCircle } from "lucide-react";

export function Loading({ label = "Loading" }) {
  return (
    <div className="state-view" role="status" aria-live="polite">
      <LoaderCircle className="state-icon state-icon-spin" size={22} aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

export function Empty({ title = "Nothing here yet", description }) {
  return (
    <div className="state-view state-view-card">
      <Inbox className="state-icon" size={24} aria-hidden="true" />
      <h3>{title}</h3>
      {description && <p>{description}</p>}
    </div>
  );
}

export function ErrorState({ title = "Something went wrong", message, onRetry }) {
  return (
    <div className="state-view state-view-error" role="alert">
      <AlertCircle className="state-icon" size={21} aria-hidden="true" />
      <div>
        <h3>{title}</h3>
        {message && <p>{message}</p>}
        {onRetry && (
          <button className="text-button" type="button" onClick={onRetry}>
            Try again
          </button>
        )}
      </div>
    </div>
  );
}

export function Warning({ title = "Notice", message }) {
  return (
    <div className="state-view state-view-warning" role="status">
      <AlertTriangle className="state-icon" size={20} aria-hidden="true" />
      <div>
        <h3>{title}</h3>
        {message && <p>{message}</p>}
      </div>
    </div>
  );
}
