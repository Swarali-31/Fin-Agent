export default function ChartCard({ title, description, action, children }) {
  return (
    <section className="surface-card chart-card">
      <div className="card-heading">
        <div>
          <h2>{title}</h2>
          {description && <p>{description}</p>}
        </div>
        {action}
      </div>
      <div className="chart-content">{children}</div>
    </section>
  );
}
