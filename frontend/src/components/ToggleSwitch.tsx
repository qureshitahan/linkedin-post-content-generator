import InfoTip from './InfoTip';

interface ToggleSwitchProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
  id?: string;
}

export function ToggleSwitch({ checked, onChange, disabled, id }: ToggleSwitchProps) {
  return (
    <button
      id={id}
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-brand-500/30 ${
        checked ? 'bg-brand-600' : 'bg-slate-300'
      } ${disabled ? 'cursor-not-allowed opacity-50' : 'cursor-pointer'}`}
    >
      <span
        className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
          checked ? 'translate-x-6' : 'translate-x-1'
        }`}
      />
    </button>
  );
}

interface ToggleRowProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  description?: string;
  suffix?: string;
  help?: string;
  disabled?: boolean;
}

export function ToggleRow({
  checked,
  onChange,
  label,
  description,
  suffix,
  help,
  disabled,
}: ToggleRowProps) {
  return (
    <div
      className={`flex items-center justify-between gap-3 rounded-lg border px-3 py-2.5 transition-colors ${
        checked ? 'border-brand-200 bg-brand-50/50' : 'border-slate-200 bg-white'
      } ${disabled ? 'opacity-60' : ''}`}
    >
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-sm font-medium text-slate-800">{label}</span>
          {suffix && (
            <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-amber-800">
              {suffix}
            </span>
          )}
          {help && <InfoTip text={help} />}
        </div>
        {description && <p className="mt-0.5 text-xs text-slate-500">{description}</p>}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <span
          className={`w-7 text-right text-xs font-semibold uppercase tracking-wide ${
            checked ? 'text-brand-700' : 'text-slate-400'
          }`}
        >
          {checked ? 'On' : 'Off'}
        </span>
        <ToggleSwitch checked={checked} onChange={onChange} disabled={disabled} />
      </div>
    </div>
  );
}
