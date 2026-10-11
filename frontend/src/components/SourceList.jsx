export default function SourceList({ sources = [], sourceIds }) {
  const visibleSources = sourceIds
    ? sources.filter((source) => sourceIds.includes(source.source_id))
    : sources;

  if (!visibleSources.length) {
    return <p className="text-sm text-slate-500">No retrieved sources were provided.</p>;
  }

  return (
    <ul className="mt-3 space-y-3">
      {visibleSources.map((source, index) => (
        <li
          className="rounded-md border border-slate-200 p-3"
          key={source.source_id ?? source.url ?? index}
        >
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <p className="font-medium text-slate-800">{source.title}</p>
              {source.publisher && (
                <p className="mt-1 text-xs text-slate-500">{source.publisher}</p>
              )}
            </div>
            {source.tier && (
              <span className="rounded-full border border-slate-200 px-2 py-1 text-xs capitalize text-slate-600">
                {source.tier}
              </span>
            )}
          </div>
          {source.snippet && <p className="mt-2 text-sm text-slate-600"><span className="font-medium">Source excerpt: </span>{source.snippet}</p>}
          {source.url && (
            <a
              className="mt-2 block break-all text-sm text-blue-700 underline"
              href={source.url}
              target="_blank"
              rel="noopener noreferrer"
            >
              {source.url}
            </a>
          )}
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
            {source.published_date && <span>Published: {source.published_date}</span>}
            {source.retrieved_at && (
              <span>Retrieved: {new Date(source.retrieved_at).toLocaleString()}</span>
            )}
            {source.source_id && <span>Source ID: {source.source_id}</span>}
          </div>
        </li>
      ))}
    </ul>
  );
}
