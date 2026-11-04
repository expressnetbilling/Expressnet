import { CreditCard, Phone, RefreshCw, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import toast from 'react-hot-toast';
import { useSearchParams } from 'react-router-dom';
import api from '../api/axios';

function formatKES(value) {
  return `KES ${Number(value || 0).toLocaleString('en-KE', { minimumFractionDigits: 2 })}`;
}

export default function Expenses() {
  const [searchParams] = useSearchParams();
  const [subscription, setSubscription] = useState(null);
  const [destination, setDestination] = useState(null);
  const [payModalOpen, setPayModalOpen] = useState(false);
  const [phone, setPhone] = useState('');
  const [paying, setPaying] = useState(false);
  const [loading, setLoading] = useState(true);

  const loadSubscription = async () => {
    setLoading(true);
    try {
      const { data } = await api.get('/subscription/status');
      setSubscription(data.subscription || null);
      setDestination(data.payment_destination || null);
    } catch (error) {
      toast.error(error.response?.data?.message || 'Failed to load subscription');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadSubscription(); }, []);
  useEffect(() => {
    if (searchParams.get('paySystem')) setPayModalOpen(true);
  }, [searchParams]);

  const paySystem = async (event) => {
    event.preventDefault();
    if (!phone.trim()) {
      toast.error('Enter the M-Pesa phone number');
      return;
    }
    setPaying(true);
    try {
      const { data } = await api.post('/subscription/status', { method: 'mpesa_stk', phone });
      toast.success(data.message || 'STK prompt sent. Complete payment on your phone.');
      setPayModalOpen(false);
      await loadSubscription();
    } catch (error) {
      toast.error(error.response?.data?.message || 'Failed to start M-Pesa payment');
    } finally {
      setPaying(false);
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-3">
        <div><h1 className="text-xl font-semibold text-black">Expenses</h1><p className="mt-1 text-sm text-slate-500">Expense records will appear here when connected to saved expense data.</p></div>
        <button type="button" className="btn-secondary h-9 px-4" onClick={() => setPayModalOpen(true)}><CreditCard size={14} />Pay system fee</button>
      </div>

      <section className="theme-card rounded-xl border p-6">
        <div className="mx-auto max-w-lg py-7 text-center">
          <p className="theme-text text-sm font-semibold">No expense records</p>
          <p className="theme-muted mt-2 text-sm">There are no saved expenses to display.</p>
        </div>
      </section>

      {destination && <section className="theme-card rounded-xl border p-5">
        <h2 className="theme-text text-sm font-semibold">Subscription payment bank account</h2>
        <p className="theme-muted mt-1 text-xs">Use these account details when paying your system subscription.</p>
        <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
          {destination.bank_name && <div><dt className="theme-muted text-xs">Bank</dt><dd className="theme-text mt-1 font-medium">{destination.bank_name}</dd></div>}
          {destination.account_name && <div><dt className="theme-muted text-xs">Account name</dt><dd className="theme-text mt-1 font-medium">{destination.account_name}</dd></div>}
          {destination.account_number && <div><dt className="theme-muted text-xs">Account number</dt><dd className="theme-text mt-1 font-medium">{destination.account_number}</dd></div>}
          {destination.branch && <div><dt className="theme-muted text-xs">Branch</dt><dd className="theme-text mt-1 font-medium">{destination.branch}</dd></div>}
        </dl>
        {destination.instructions && <p className="theme-muted mt-3 whitespace-pre-line text-xs">{destination.instructions}</p>}
      </section>}

      {payModalOpen && <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4">
        <section className="theme-card w-full max-w-md rounded-xl border p-5 shadow-xl">
          <div className="flex items-start justify-between gap-3"><div><h2 className="theme-text text-base font-semibold">Pay system subscription</h2><p className="theme-muted mt-1 text-xs">Enter the M-Pesa number that should receive the payment prompt.</p></div><button type="button" className="theme-muted" onClick={() => setPayModalOpen(false)} aria-label="Close"><X size={18} /></button></div>
          {loading ? <p className="theme-muted mt-5 text-sm">Loading subscription...</p> : <>
            <div className="theme-card-muted mt-4 rounded-lg border p-3"><p className="theme-muted text-xs">Amount due</p><p className="theme-text mt-1 text-lg font-semibold">{formatKES(subscription?.amount)}</p><p className="theme-muted mt-2 text-xs">System fee: {subscription?.system_fee_percent ?? 0}% of this month&apos;s successful internet sales ({formatKES(subscription?.system_fee_sales_basis)}).</p></div>
            {destination && <div className="theme-card-muted mt-3 rounded-lg border p-3 text-xs"><p className="theme-text font-semibold">Bank transfer option</p><p className="theme-muted mt-1">{destination.bank_name || ''}{destination.account_name ? ` · ${destination.account_name}` : ''}{destination.account_number ? ` · ${destination.account_number}` : ''}</p></div>}
            <form className="mt-4" onSubmit={paySystem}><label className="form-label">M-Pesa phone number<div className="relative mt-1"><Phone size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400"/><input className="form-input mt-0 pl-9" value={phone} onChange={(event) => setPhone(event.target.value)} placeholder="07XXXXXXXX or 2547XXXXXXXX" /></div></label><div className="mt-4 flex justify-end gap-2"><button type="button" className="btn-secondary" onClick={loadSubscription} disabled={loading || paying}><RefreshCw size={14}/>Refresh</button><button type="submit" className="btn-primary" disabled={loading || paying}>{paying ? 'Sending prompt...' : 'Send payment prompt'}</button></div></form>
          </>}
        </section>
      </div>}
    </div>
  );
}
