import { CheckCircle2, ExternalLink, PlugZap, Save, Send } from 'lucide-react';
import { useEffect, useState } from 'react';
import toast from 'react-hot-toast';
import adminApi from '../../api/adminAxios';

const MASKED = '********';

export default function AdminIntegrations() {
  const [form, setForm] = useState({
    notification_provider: 'slek',
    whatsapp_enabled: true,
    apiwap_base_url: 'https://api.apiwap.com/api/v1',
    apiwap_api_key: '',
    test_phone: '',
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const { data } = await adminApi.get('/admin/integrations');
      setForm((current) => ({
        ...current,
        notification_provider: data.notification_provider || 'slek',
        whatsapp_enabled: data.whatsapp_enabled !== false,
        apiwap_base_url: data.apiwap_base_url || 'https://api.apiwap.com/api/v1',
        apiwap_api_key: data.has_apiwap_api_key ? MASKED : '',
      }));
    } catch (error) {
      toast.error(error.response?.data?.error || error.response?.data?.message || 'Failed to load integrations');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const update = (event) => {
    const { name, type, checked, value } = event.target;
    setForm((current) => ({ ...current, [name]: type === 'checkbox' ? checked : value }));
  };

  const save = async () => {
    setSaving(true);
    try {
      const { data } = await adminApi.patch('/admin/integrations', form);
      toast.success(data.message || 'Integration settings saved');
      setForm((current) => ({ ...current, apiwap_api_key: data.has_apiwap_api_key ? MASKED : '' }));
    } catch (error) {
      toast.error(error.response?.data?.error || error.response?.data?.message || 'Failed to save integrations');
    } finally {
      setSaving(false);
    }
  };

  const test = async () => {
    if (!form.test_phone.trim()) {
      toast.error('Enter a phone number for the test');
      return;
    }
    setTesting(true);
    try {
      const { data } = await adminApi.post('/admin/integrations', {
        provider: form.notification_provider,
        phone: form.test_phone,
        apiwap_base_url: form.apiwap_base_url,
        apiwap_api_key: form.apiwap_api_key,
        message: 'ApiWap test notification from Expressnet admin.',
      });
      toast.success(data.message || 'Integration test sent');
    } catch (error) {
      toast.error(error.response?.data?.error || error.response?.data?.message || 'Integration test failed');
    } finally {
      setTesting(false);
    }
  };

  if (loading) return <p className="text-xs text-slate-600">Loading integrations...</p>;

  const connected = form.apiwap_api_key === MASKED;

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="page-title">Integrations</h1>
          <p className="page-subtitle">Manage platform integrations and notification providers.</p>
        </div>
        <button type="button" className="btn-primary" onClick={save} disabled={saving}>
          <Save size={16} />
          {saving ? 'Saving...' : 'Save Changes'}
        </button>
      </div>

      <section className="theme-card rounded-lg border p-5 shadow-sm">
        <div className="flex items-center justify-between gap-3">
          <h2 className="theme-text flex items-center gap-2 text-sm font-semibold"><PlugZap size={17} /> WhatsApp Provider</h2>
          <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${connected ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-600'}`}>
            {connected ? 'ApiWap key saved' : 'ApiWap not configured'}
          </span>
        </div>

        <div className="mt-4 grid gap-4 md:grid-cols-2">
          <label className="form-label">Provider
            <select name="notification_provider" className="form-input" value={form.notification_provider} onChange={update}>
              <option value="slek">Slek</option>
              <option value="apiwap">ApiWap</option>
            </select>
          </label>
          <label className="form-label">ApiWap base URL
            <input name="apiwap_base_url" className="form-input" value={form.apiwap_base_url} onChange={update} />
          </label>
          <label className="form-label md:col-span-2">ApiWap API key
            <input name="apiwap_api_key" type="password" className="form-input" value={form.apiwap_api_key} onChange={update} placeholder="Paste ApiWap API key" autoComplete="off" />
          </label>
          <label className="flex items-center gap-3 rounded-md border border-slate-200 bg-slate-50 p-3 text-sm font-semibold text-slate-700 md:col-span-2">
            <input type="checkbox" name="whatsapp_enabled" checked={form.whatsapp_enabled} onChange={update} />
            Enable WhatsApp notifications platform-wide
          </label>
        </div>

        <div className="mt-4 flex flex-col gap-3 rounded-md border border-slate-200 bg-slate-50 p-4 sm:flex-row sm:items-end">
          <label className="form-label flex-1">Test phone number
            <input name="test_phone" className="form-input" value={form.test_phone} onChange={update} placeholder="2547XXXXXXXX" />
          </label>
          <button type="button" className="btn-secondary justify-center" onClick={test} disabled={testing}>
            <Send size={15} />
            {testing ? 'Testing...' : 'Test'}
          </button>
          <a href="https://account.apiwap.com/register" target="_blank" rel="noreferrer" className="btn-secondary justify-center text-violet-600">
            <ExternalLink size={15} />
            Get API Key
          </a>
        </div>

        <p className="mt-3 flex items-center gap-2 text-xs text-slate-500">
          <CheckCircle2 size={14} className={connected ? 'text-emerald-500' : 'text-slate-400'} />
          ApiWap is used when the provider is set to ApiWap and an API key is saved.
        </p>
      </section>
    </div>
  );
}
