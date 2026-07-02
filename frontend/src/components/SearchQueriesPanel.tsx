import type { SearchQuery } from '../types';

interface Props {
  queries: SearchQuery[];
  status: string;
}

export default function SearchQueriesPanel({ queries, status }: Props) {
  if (queries.length === 0) return null;

  return (
    <div className="card">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-slate-900">Expanded Search Queries</h2>
        <span className="badge bg-blue-100 text-blue-800">{status}</span>
      </div>
      <p className="mb-4 text-sm text-slate-500">
        Your goal was expanded into search queries run across News, Reddit, Hacker News, X, and
        other enabled sources. <span className="font-medium">Gathered</span> is raw results before
        filtering; <span className="font-medium">On-topic</span> is what matched your goal after
        relevance filtering.
      </p>

      <div className="overflow-hidden rounded-lg border border-slate-200">
        <table className="w-full text-sm">
          <thead className="bg-slate-50">
            <tr>
              <th className="px-4 py-2 text-left font-medium text-slate-600">Query</th>
              <th className="px-4 py-2 text-right font-medium text-slate-600">Gathered</th>
              <th className="px-4 py-2 text-right font-medium text-slate-600">On-Topic</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {queries.map((q) => (
              <tr key={q.id} className="hover:bg-slate-50">
                <td className="px-4 py-2.5 font-medium text-slate-800">{q.query_text}</td>
                <td className="px-4 py-2.5 text-right tabular-nums text-slate-500">
                  {q.raw_post_count !== null && q.raw_post_count !== undefined
                    ? q.raw_post_count.toLocaleString()
                    : '—'}
                </td>
                <td className="px-4 py-2.5 text-right tabular-nums text-slate-600">
                  {q.post_count !== null ? q.post_count.toLocaleString() : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
