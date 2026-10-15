import { ArrowDownRight, ArrowUpRight } from "lucide-react";

export default function MetricCard({
  label,
  value,
  detail,
  trend,
  tone = "neutral",
}) {
  return (
    <article className="metric-card">
      <p className="metric-label">{label}</p>
      <p className="metric-value">{value}</p>
      {(detail || trend) && (
        <div className={`metric-detail metric-detail-${tone}`}>
          {trend === "up" && <ArrowUpRight size={15} aria-hidden="true" />}
          {trend === "down" && <ArrowDownRight size={15} aria-hidden="true" />}
          <span>{detail}</span>
        </div>
      )}
    </article>
  );
}
