import { ShoppingBag } from 'lucide-react';

export default function Salary() {
  return (
    <section className="theme-card rounded-xl border p-6 sm:p-8">
      <div className="mx-auto max-w-lg py-8 text-center">
        <span className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl" style={{ background: 'var(--app-accent-muted)', color: 'var(--app-accent)' }}>
          <ShoppingBag size={22} />
        </span>
        <h1 className="theme-text mt-4 text-lg font-semibold">Salary records</h1>
        <p className="theme-muted mt-2 text-sm">No salary records are available. Salary entries will appear here when connected to saved payroll data.</p>
      </div>
    </section>
  );
}
