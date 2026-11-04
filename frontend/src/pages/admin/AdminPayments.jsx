import { Building2, Save } from 'lucide-react';
import { useEffect, useState } from 'react';
import toast from 'react-hot-toast';
import adminApi from '../../api/adminAxios';

const initialForm = {
  subscription_bank_name: '',
  subscription_bank_account_name: '',
  subscription_bank_account_number: '',
  subscription_bank_branch: '',
  subscription_payment_instructions: '',
};

export default function AdminPayments() {
  const [form, setForm] = useState(initialForm);
  const [feePercent, setFeePercent] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    adminApi.get('/admin/site').then(({ data }) => {
      setForm(Object.fromEntries(Object.keys(initialForm).map((key) => [key, data[key] || ''])));
      setFeePercent(data.system_subscription_fee_percent);
    }).catch((error) => {
      toast.error(error.response?.data?.message || 'Could not load subscription payment settings');
    }).finally(() => setLoading(false));
  }, []);

  const update = (key, value) => setForm((current) => ({ ...current, [key]: value }));
  const save = async (event) => {
    event.preventDefault();
    setSaving(true);
    try {
      await adminApi.patch('/admin/site', form);
      toast.success('Subscription payment account saved');
    } catch (error) {
      toast.error(error.response?.data?.message || 'Could not save subscription payment account');
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={save} className="space-y-6">
      <div><p className="admin-accent-label text-[10px] font-bold uppercase tracking-[0.18em]">Platform finance</p><h2 className="admin-heading mt-1 text-2xl font-bold tracking-tight">Subscription payments</h2><p className="admin-muted mt-1 text-sm">Set the bank account tenants should use for system subscription payments.</p></div>
      <section className="admin-card overflow-hidden rounded-2xl border shadow-[0_16px_48px_rgba(15,23,42,0.06)]">
        <div className="border-b border-slate-200/70 px-5 py-4"><h3 className="admin-heading flex items-center gap-2 text-sm font-bold"><Building2 size={16} className="admin-accent-text"/>Receiving bank account</h3><p className="admin-muted mt-1 text-xs">The details saved here are shown to tenants on their subscription payment screens.</p></div>
        {loading ? <p className="admin-muted p-5 text-sm">Loading payment settings...</p> : <div className="grid gap-4 p-5 sm:grid-cols-2">
          <label className="text-xs font-semibold text-slate-600">Bank name<input className="admin-input mt-1 h-10 w-full rounded-lg border px-3 text-sm" value={form.subscription_bank_name} onChange={(event) => update('subscription_bank_name', event.target.value)} placeholder="Select or enter bank name" /></label>
          <label className="text-xs font-semibold text-slate-600">Account name<input className="admin-input mt-1 h-10 w-full rounded-lg border px-3 text-sm" value={form.subscription_bank_account_name} onChange={(event) => update('subscription_bank_account_name', event.target.value)} placeholder="Name on account" /></label>
          <label className="text-xs font-semibold text-slate-600">Account number<input className="admin-input mt-1 h-10 w-full rounded-lg border px-3 text-sm" value={form.subscription_bank_account_number} onChange={(event) => update('subscription_bank_account_number', event.target.value)} placeholder="Receiving account number" /></label>
          <label className="text-xs font-semibold text-slate-600">Branch<input className="admin-input mt-1 h-10 w-full rounded-lg border px-3 text-sm" value={form.subscription_bank_branch} onChange={(event) => update('subscription_bank_branch', event.target.value)} placeholder="Bank branch (optional)" /></label>
          <label className="text-xs font-semibold text-slate-600 sm:col-span-2">Payment instructions<textarea className="admin-input mt-1 min-h-24 w-full rounded-lg border px-3 py-2 text-sm" value={form.subscription_payment_instructions} onChange={(event) => update('subscription_payment_instructions', event.target.value)} placeholder="Tell tenants what reference or payment confirmation to include." /></label>
        </div>}
        <div className="flex flex-col gap-3 border-t border-slate-200/70 px-5 py-4 sm:flex-row sm:items-center sm:justify-between"><p className="admin-muted text-xs">System subscription charge: <strong className="admin-heading">{feePercent === null ? 'Loading...' : `${feePercent}%`}</strong> of successful tenant internet sales, as configured by <code>SYSTEM_SUBSCRIPTION_FEE_PERCENT</code>.</p><button type="submit" className="admin-accent-button inline-flex h-10 items-center justify-center gap-2 rounded-lg px-4 text-xs font-bold text-white disabled:opacity-60" disabled={loading || saving}>{saving ? 'Saving...' : <><Save size={14}/>Save account</>}</button></div>
      </section>
    </form>
  );
}
