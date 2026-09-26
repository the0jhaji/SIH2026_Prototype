import { NAV_ITEMS, type ViewKey } from './nav'

interface Props {
  active: ViewKey
  onNavigate: (key: ViewKey) => void
}

const ACTIVE = 'border-primary bg-primary/15 text-primary'
const INACTIVE =
  'border-transparent text-on-surface-variant hover:border-outline-variant/40 hover:bg-surface-container-high hover:text-on-surface'

/**
 * Fixed-width rail that spans the full shell height. It is a grid area of
 * `.app-shell`, not `position: fixed`, so it can never overlap or be
 * overlapped by page content.
 */
export function Sidebar({ active, onNavigate }: Props) {
  return (
    <aside className="app-nav flex flex-col items-center border-r border-outline-variant/50 bg-surface-container-low">
      <div className="flex h-full w-full flex-col items-center gap-2 overflow-y-auto px-1.5 py-2.5">
        <div
          className="mb-1 flex h-8 w-8 shrink-0 items-center justify-center border border-primary/60 bg-primary/10 font-mono text-sm text-primary"
          title="ASTRA"
        >
          ✦
        </div>

        <nav className="flex w-full flex-1 flex-col gap-1" aria-label="Primary">
          {NAV_ITEMS.map(item => {
            const isActive = active === item.key
            return (
              <button
                key={item.key}
                type="button"
                onClick={() => onNavigate(item.key)}
                aria-current={isActive ? 'page' : undefined}
                className={`flex w-full shrink-0 flex-col items-center gap-0.5 border px-1 py-1.5 transition ${isActive ? ACTIVE : INACTIVE}`}
                title={item.label}
              >
                <span className="msym text-xl leading-none" aria-hidden="true">
                  {item.icon}
                </span>
                <span className="font-mono text-[9px] font-bold uppercase leading-none tracking-wide">
                  {item.label}
                </span>
              </button>
            )
          })}
        </nav>
      </div>
    </aside>
  )
}
