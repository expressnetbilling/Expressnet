import { Mail } from 'lucide-react';

export default function Emails() {
  return (
    <section className="theme-card rounded-xl border p-6 sm:p-8">
      <div className="mx-auto max-w-lg py-8 text-center">
        <span className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl" style={{ background: 'var(--app-accent-muted)', color: 'var(--app-accent)' }}>
          <Mail size={22} />
        </span>
        <h1 className="theme-text mt-4 text-lg font-semibold">Email templates</h1>
        <p className="theme-muted mt-2 text-sm">No email templates are configured. Templates will appear here when connected to saved email settings.</p>
      </div>
    </section>
  );
}
