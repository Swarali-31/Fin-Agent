export default function DataTable({
  columns,
  rows,
  getRowKey,
  emptyTitle = "No records found",
}) {
  if (!rows?.length) {
    return (
      <div className="table-empty" role="status">
        {emptyTitle}
      </div>
    );
  }

  return (
    <div className="table-scroll">
      <table className="data-table">
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key} scope="col" className={column.numeric ? "text-right" : ""}>
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={getRowKey?.(row) ?? row.id ?? index}>
              {columns.map((column) => (
                <td
                  key={column.key}
                  className={`${column.numeric ? "text-right tabular-nums" : ""} ${column.className ?? ""}`}
                >
                  {column.render ? column.render(row) : row[column.key]}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
