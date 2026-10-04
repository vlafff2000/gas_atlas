// Справка «Форматы данных»: вкладки по модулям, тексты — в helpTexts.ts.
import { useState } from 'react'
import { HELP_TABS, type HelpBlock } from './helpTexts'
import './help.css'

function Block({ b }: { b: HelpBlock }) {
  return (
    <section className="help-block">
      {b.h && <h3>{b.h}</h3>}
      {b.p && <p>{b.p}</p>}
      {b.list && <ul>{b.list.map((t, i) => <li key={i}>{t}</li>)}</ul>}
      {b.table && (
        <div className="help-table">
          <table>
            <thead><tr>{b.table.head.map((h, i) => <th key={i}>{h}</th>)}</tr></thead>
            <tbody>{b.table.rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j}>{c}</td>)}</tr>)}</tbody>
          </table>
        </div>
      )}
      {b.example && (
        <div className="help-table example">
          <table>
            <thead><tr>{b.example.head.map((h, i) => <th key={i}>{h}</th>)}</tr></thead>
            <tbody>{b.example.rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j}>{c}</td>)}</tr>)}</tbody>
          </table>
          {b.example.note && <p className="help-note">{b.example.note}</p>}
        </div>
      )}
      {b.warn && <div className="note warning">{b.warn}</div>}
    </section>
  )
}

/** Адрес вкладки: «#/@help/gdi»; без вкладки открываются «Общие правила». */
export function HelpPage({ tab }: { tab: string }) {
  const [current, setCurrent] = useState(HELP_TABS.some(t => t.id === tab) ? tab : HELP_TABS[0].id)
  const active = HELP_TABS.find(t => t.id === current) ?? HELP_TABS[0]
  const go = (id: string) => { setCurrent(id); history.replaceState(null, '', '#/@help/' + id) }
  return (
    <div className="help">
      <header className="module-title">
        <div>
          <h1>Справка: форматы данных</h1>
          <p className="lede">Какие файлы и колонки принимает каждый модуль. Загрузка данных — в разделе <a href="#/@import">«Импорт данных»</a>.</p>
        </div>
      </header>
      <div className="tabs" role="tablist">
        {HELP_TABS.map(t => (
          <button key={t.id} type="button" role="tab" aria-selected={t.id === active.id} onClick={() => go(t.id)}>{t.title}</button>
        ))}
      </div>
      <div className="help-body" role="tabpanel">
        <p className="lede">{active.lede}</p>
        {active.blocks.map((b, i) => <Block key={i} b={b} />)}
      </div>
    </div>
  )
}
