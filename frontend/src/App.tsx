import { EventLog } from './components/EventLog'
import { Header } from './components/Header'
import { LiveFeed } from './components/LiveFeed'
import { StatusPanel } from './components/StatusPanel'
import { StepChecklist } from './components/StepChecklist'
import { useExperiment } from './hooks/useExperiment'

export default function App() {
  const { state, start, stop } = useExperiment()

  return (
    <div className="min-h-screen bg-slate-950 text-slate-200">
      <Header state={state} onStart={start} onStop={stop} />
      <main className="mx-auto grid max-w-7xl grid-cols-1 gap-4 p-4 xl:grid-cols-3">
        <section className="space-y-4 xl:col-span-2">
          <LiveFeed state={state} />
        </section>
        <div className="space-y-4">
          <StatusPanel state={state} />
          <StepChecklist state={state} />
        </div>
        <section className="xl:col-span-3">
          <EventLog events={state.log} />
        </section>
      </main>
    </div>
  )
}