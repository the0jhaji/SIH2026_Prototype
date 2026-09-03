import { NAV_ITEMS, type ViewKey } from './nav'

interface Props {
  active: ViewKey
  onNavigate: (key: ViewKey) => void
}

const ACTIVE =
  'bg-primary-container text-on-primary-container'
const INACTIVE = 'text-on-surface-variant hover:bg-surface-container-high'

export function Sidebar({ active, onNavigate }: Props) {
  return (
    <aside className="fixed inset-y-0 left-0 z-40 flex w-24 flex-col items-center border-r border-outline-variant/50 bg-surface-container-low py-4">
      <div className="mb-6 flex h-12 w-12 items-center justify-center border border-primary/60 bg-primary/10 font-mono text-lg text-primary">
        ✦
      </div>

      <nav className="flex flex-1 flex-col gap-1">
        {NAV_ITEMS.map(item => (
          <button
            key={item.key}
            type="button"
            onClick={() => onNavigate(item.key)}
            className={`flex w-16 flex-col items-center gap-1 border px-2 py-2.5 transition ${
              active === item.key ? ACTIVE : INACTIVE
            }`}
            title={item.label}
          >
            <span className="msym text-2xl leading-none" aria-hidden="true">
              {item.icon}
            </span>
            <span className="font-mono text-[9px] font-bold uppercase tracking-widest">
              {item.label}
            </span>
          </button>
        ))}
      </nav>
    </aside>
  )
}
