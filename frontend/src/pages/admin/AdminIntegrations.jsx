import { Check, ChevronRight, CreditCard, MessageCircle, PlugZap, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import toast from 'react-hot-toast';
import adminApi from '../../api/adminAxios';

const initialState = {
  notification_provider: 'slek',
  collection_provider: 'daraja',
  apiwap_configured: false,
  slek_configured: false,
};

const providerOptions = {
  payments: [
    { id: 'daraja', name: 'Daraja', region: 'M-Pesa', description: 'Accept customer payments through Safaricom Daraja.' },
  ],
  communications: [
    { id: 'apiwap', name: 'ApiWap', region: 'WhatsApp', description: 'Send WhatsApp messages through the ApiWap gateway.' },
    { id: 'slek', name: 'Slek', region: 'WhatsApp', description: 'Send WhatsApp messages through the Slek gateway.' },
  ],
};

function ProviderDialog({ kind, selected, configured, saving, onSelect, onClose, onSave }) {
  const isPayments = kind === 'payments';
  const options = providerOptions[kind];
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/70 p-4 backdrop-blur-sm" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section role="dialog" aria-modal="true" aria-labelledby="integration-dialog-title" className="admin-card w-full max-w-lg overflow-hidden rounded-2xl border shadow-2xl">
        <header className="flex items-start justify-between border-b border-slate-200/70 px-5 py-4"><div><p className="admin-accent-label text-[10px] font-bold uppercase tracking-[0.16em]">Integration setup</p><h2 id="integration-dialog-title" className="admin-heading mt-1 text-base font-bold">Choose {isPayments ? 'payment provider' : 'communication provider'}</h2><p className="admin-muted mt-1 text-xs">Provider credentials and endpoints are managed by the platform environment.</p></div><button type="button" onClick={onClose} aria-label="Close dialog" className="admin-muted rounded-lg p-2 hover:bg-slate-100"><X size={18} /></button></header>
        <div className="space-y-3 p-5">{options.map((option) => {
          const active = selected === option.id;
          const ready = configured[option.id];
          return <button key={option.id} type="button" onClick={() => onSelect(option.id)} className={`admin-provider-option flex w-full items-center gap-3 rounded-xl border p-4 text-left transition ${active ? 'is-selected' : ''}`}>
            <span className={`admin-provider-icon flex h-11 w-11 shrink-0 items-center justify-center rounded-xl ${active ? 'is-selected' : ''}`}>{isPayments ? <CreditCard size={20} /> : <MessageCircle size={20} />}</span>
            <span className="min-w-0 flex-1"><span className="flex items-center gap-2"><span className="admin-heading text-sm font-semibold">{option.name}</span><span className="admin-muted text-[10px]">{option.region}</span></span><span className="admin-muted mt-1 block text-xs">{option.description}</span><span className={`mt-2 inline-flex rounded-full px-2 py-1 text-[9px] font-semibold ${ready ? 'bg-emerald-500/15 text-emerald-500' : 'bg-slate-500/15 text-slate-400'}`}>{ready ? 'Environment configured' : 'Check environment config'}</span></span>
            <span className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full border ${active ? 'admin-provider-check' : 'border-slate-400/50'}`}>{active && <Check size={13} />}</span>
          </button>;
        })}</div>
        <footer className="flex justify-end gap-2 border-t border-slate-200/70 px-5 py-4"><button type="button" onClick={onClose} className="admin-muted rounded-lg px-4 py-2 text-xs font-semibold hover:bg-slate-500/10">Cancel</button><button type="button" onClick={onSave} disabled={saving} className="admin-primary rounded-lg px-4 py-2 text-xs font-semibold text-white disabled:opacity-60">{saving ? 'Saving…' : 'Save selection'}</button></footer>
      </section>
    </div>
  );
}

function IntegrationCard({ title, description, provider, region, icon: Icon, onClick }) {
  return <button type="button" onClick={onClick} className="admin-integration-card group rounded-2xl border p-5 text-left transition duration-200 hover:-translate-y-0.5 hover:shadow-xl">
    <div className="flex items-start gap-3"><span className="admin-integration-icon flex h-11 w-11 items-center justify-center rounded-xl"><Icon size={20} /></span><span className="min-w-0 flex-1"><span className="admin-heading block text-sm font-semibold">{title}</span><span className="admin-muted mt-1 block text-xs">{description}</span></span><span className="admin-provider-check flex h-6 w-6 items-center justify-center rounded-full"><Check size={13} /></span></div>
    <div className="mt-5 flex items-center justify-between"><span className="admin-accent-text text-xs font-semibold">Configure <ChevronRight size={14} className="ml-1 inline" /></span><span className="admin-muted rounded-full bg-slate-500/10 px-2.5 py-1 text-[10px] font-medium">{provider} · {region}</span></div>
  </button>;
}

export default function AdminIntegrations() {
  const [settings, setSettings] = useState(initialState);
  const [draft, setDraft] = useState(initialState);
  const [dialog, setDialog] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const { data } = await adminApi.get('/admin/integrations');
      const next = {
        notification_provider: data.notification_provider || 'slek',
        collection_provider: data.collection_provider || 'daraja',
        apiwap_configured: Boolean(data.apiwap_configured ?? data.has_apiwap_api_key),
        slek_configured: Boolean(data.slek_configured),
      };
      setSettings(next);
      setDraft(next);
    } catch (error) {
      toast.error(error.response?.data?.error || error.response?.data?.message || 'Failed to load integrations');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  const save = async () => {
    setSaving(true);
    try {
      const { data } = await adminApi.patch('/admin/integrations', {
        notification_provider: draft.notification_provider,
        collection_provider: draft.collection_provider,
      });
      const next = { ...draft, collection_provider: 'daraja' };
      setSettings(next);
      setDraft(next);
      toast.success(data.message || 'Integration provider saved');
      setDialog(null);
    } catch (error) {
      toast.error(error.response?.data?.error || error.response?.data?.message || 'Failed to save integration provider');
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <div className="grid gap-4 sm:grid-cols-2"><div className="h-32 animate-pulse rounded-2xl bg-white/5" /><div className="h-32 animate-pulse rounded-2xl bg-white/5" /></div>;

  const paymentName = 'Daraja';
  const communicationName = settings.notification_provider === 'apiwap' ? 'ApiWap' : 'Slek';
  const configuration = { daraja: true, apiwap: settings.apiwap_configured, slek: settings.slek_configured };

  return <div className="space-y-6">
    <div><p className="admin-accent-label text-[10px] font-bold uppercase tracking-[0.18em]">Platform services</p><h2 className="admin-heading mt-1 text-2xl font-bold tracking-tight">Integrations</h2><p className="admin-muted mt-1 text-sm">Choose which platform providers handle payments and communications.</p></div>
    <section><div className="mb-3"><h3 className="admin-heading text-sm font-bold">Core integrations</h3><p className="admin-muted mt-1 text-xs">Select a provider to view or change the active integration.</p></div><div className="grid gap-4 md:grid-cols-2">
      <IntegrationCard title="Customer payments" description="Payment collection across customer checkout." provider={paymentName} region="M-Pesa" icon={CreditCard} onClick={() => { setDraft(settings); setDialog('payments'); }} />
      <IntegrationCard title="Customer communications" description="WhatsApp messages sent by platform workflows." provider={communicationName} region="WhatsApp" icon={MessageCircle} onClick={() => { setDraft(settings); setDialog('communications'); }} />
    </div></section>
    <p className="admin-muted text-xs">Provider keys and API endpoints are read from the server environment. This page only selects the active provider.</p>
    {dialog && <ProviderDialog kind={dialog} selected={dialog === 'payments' ? 'daraja' : draft.notification_provider} configured={configuration} saving={saving} onSelect={(id) => setDraft((current) => ({ ...current, [dialog === 'payments' ? 'collection_provider' : 'notification_provider']: id }))} onClose={() => setDialog(null)} onSave={save} />}
  </div>;
}
