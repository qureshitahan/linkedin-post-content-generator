interface Props {
  text: string;
  /** Use on dark pill backgrounds (selected source/style chips). */
  onDark?: boolean;
}

/** Small (i) icon — hover or focus to read the explanation. */
export default function InfoTip({ text, onDark = false }: Props) {
  const btnClass = onDark
    ? 'bg-white/25 text-white hover:bg-white/40'
    : 'bg-slate-200 text-slate-600 hover:bg-slate-300';

  return (
    <span className="group relative ml-0.5 inline-flex align-middle">
      <button
        type="button"
        onClick={(e) => e.preventDefault()}
        className={`inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[10px] font-bold leading-none focus:outline-none focus:ring-2 focus:ring-brand-500 focus:ring-offset-1 ${btnClass}`}
        aria-label="More information"
        title={text}
      >
        i
      </button>
      <span
        role="tooltip"
        className="pointer-events-none absolute bottom-full left-1/2 z-20 mb-2 hidden w-56 -translate-x-1/2 rounded-lg bg-slate-800 px-3 py-2 text-left text-xs font-normal leading-snug text-white shadow-lg group-hover:block group-focus-within:block sm:w-64"
      >
        {text}
      </span>
    </span>
  );
}
