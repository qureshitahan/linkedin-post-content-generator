import type { HealthStatus } from '../types';

interface Props {
  health: HealthStatus | null;
}

export default function Header({ health }: Props) {
  return (
    <header className="border-b border-slate-200 bg-white">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-4">
        <div>
          <h1 className="text-xl font-bold text-brand-900">LinkedIn Content Intelligence</h1>
          <p className="text-sm text-slate-500">Multi-source, relevance-first trend discovery</p>
        </div>
        {health && (
          <div className="flex flex-wrap justify-end gap-2">
            <span className="badge bg-green-100 text-green-800">News Ready</span>
            <span className="badge bg-green-100 text-green-800">Industry RSS Ready</span>
            <span className="badge bg-green-100 text-green-800">Hacker News Ready</span>
            {health.arxiv_configured && (
              <span className="badge bg-green-100 text-green-800">arXiv Ready</span>
            )}
            {health.pubmed_configured && (
              <span className="badge bg-green-100 text-green-800">PubMed Ready</span>
            )}
            {health.preprint_configured && (
              <span className="badge bg-green-100 text-green-800">Preprints Ready</span>
            )}
            {health.devto_configured && (
              <span className="badge bg-green-100 text-green-800">Dev.to Ready</span>
            )}
            {health.x_research_configured && (
              <span className="badge bg-purple-100 text-purple-800">X Research Buzz</span>
            )}
            {health.reddit_configured && (
              <span className="badge bg-green-100 text-green-800">Reddit Connected</span>
            )}
            <span
              className={`badge ${health.x_api_configured ? 'bg-green-100 text-green-800' : 'bg-slate-200 text-slate-600'}`}
            >
              X {health.x_api_configured ? 'Connected' : 'Optional'}
            </span>
            <span
              className={`badge ${health.anthropic_configured ? 'bg-green-100 text-green-800' : 'bg-amber-100 text-amber-800'}`}
            >
              Claude {health.anthropic_configured ? 'Connected' : 'Not configured'}
            </span>
            <span
              className={`badge ${health.image_generation_ready ? 'bg-green-100 text-green-800' : health.openai_configured ? 'bg-amber-100 text-amber-800' : 'bg-slate-200 text-slate-600'}`}
            >
              Images {health.image_generation_ready ? 'Ready' : health.openai_configured ? 'Add Claude' : 'DALL-E optional'}
            </span>
          </div>
        )}
      </div>
    </header>
  );
}
