import { AlarmClock, Bell, MessageCircle, PlugZap, Save, ShoppingCart } from 'lucide-react';
import { useEffect, useState } from 'react';
import toast from 'react-hot-toast';
import adminApi from '../../api/adminAxios';

const icons = {
  whatsapp_on_customer_created: PlugZap,
  sms_on_payment: ShoppingCart,
  whatsapp_on_expiry: AlarmClock,
  sms_on_maintenance: AlarmClock,
  sms_on_promotions: MessageCircle,
};

function Toggle({ checked, onChange }) {
  return (
    <button type="button" role="switch" aria-checked={checked} onClick={onChange} className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition ${checked ? 'bg-violet-600' : 'bg-slate-200'}`}>
      <span className={`h-4 w-4 rounded-full bg-white shadow transition-transform ${checked ? 'translate-x-6' : 'translate-x-1'}`} />
    </button>
  );
}

export default function AdminCommunications() {
  const [types, setTypes] = useState([]);
  const [form, setForm] = useState({ whatsapp_enabled: true, sms_enabled: true });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const { data } = await adminApi.get('/admin/communications');
      setTypes(data.notification_types || []);
      const next = {
        whatsapp_enabled: data.whatsapp_enabled !== false,
        sms_enabled: data.sms_enabled !== false,
      };
      (data.notification_types || []).forEach((item) => {
        next[item.key] = item.enabled !== false;
      });
      setForm(next);
    } catch (error) {
      toast.error(error.response?.data?.error || error.response?.data?.message || 'Failed to load communication settings');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const toggle = (key) => {
    setForm((current) => ({ ...current, [key]: !current[key] }));
  };

  const save = async () => {
    setSaving(true);
    try {
      await adminApi.patch('/admin/communications', form);
      toast.success('Communication settings saved');
      await load();
    } catch (error) {
      toast.error(error.response?.data?.error || error.response?.data?.message || 'Failed to save communication settings');
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <p className="text-xs text-slate-600">Loading communications...</p>;

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="page-title">Communications</h1>
          <p className="page-subtitle">Manage platform notification channels and the five system notification types.</p>
        </div>
        <button type="button" className="btn-primary" onClick={save} disabled={saving}>
          <Save size={16} />
          {saving ? 'Saving...' : 'Save Changes'}
        </button>
      </div>

      <section className="theme-card rounded-lg border p-5 shadow-sm">
        <h2 className="theme-text flex items-center gap-2 text-sm font-semibold"><Bell size={17} /> Channels</h2>
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          {[
            ['whatsapp_enabled', 'WhatsApp notifications'],
            ['sms_enabled', 'SMS notifications'],
          ].map(([key, label]) => (
            <div key={key} className="flex items-center justify-between rounded-md border border-slate-200 p-4">
              <span className="text-sm font-semibold text-slate-900">{label}</span>
              <Toggle checked={form[key]} onChange={() => toggle(key)} />
            </div>
          ))}
        </div>
      </section>

      <section className="theme-card rounded-lg border p-5 shadow-sm">
        <h2 className="theme-text text-sm font-semibold">Notification Types</h2>
        <div className="mt-4 grid gap-3">
          {types.map((item) => {
            const Icon = icons[item.key] || Bell;
            return (
              <div key={item.key} className="rounded-lg border border-slate-200 p-4">
                <div className="flex items-start justify-between gap-4">
                  <div className="flex items-start gap-3">
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-violet-50 text-violet-600"><Icon size={17} /></span>
                    <div>
                      <h3 className="text-sm font-semibold text-slate-900">{item.name}</h3>
                      <p className="mt-1 text-xs text-slate-500">{item.description}</p>
                    </div>
                  </div>
                  <Toggle checked={form[item.key]} onChange={() => toggle(item.key)} />
                </div>
                <pre className="mt-3 whitespace-pre-wrap rounded-md border border-slate-100 bg-slate-50 p-3 text-xs leading-relaxed text-slate-700">{item.message}</pre>
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}
