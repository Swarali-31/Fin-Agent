const statusStyles = {
  success: "status-success",
  partial: "status-warning",
  warning: "status-warning",
  failed: "status-danger",
  error: "status-danger",
  pending: "status-neutral",
  running: "status-info",
  neutral: "status-neutral",
};

export default function StatusBadge({ status, label }) {
  const readableLabel = label ?? status;
  const style = statusStyles[String(status).toLowerCase()] ?? "status-neutral";

  return (
    <span className={`status-badge ${style}`} aria-label={`Status: ${readableLabel}`}>
      <span className="status-dot" aria-hidden="true" />
      {readableLabel}
    </span>
  );
}
