import { CheckCheck, ChevronDown, Coins, MoreVertical, Plus, Search, X, Settings2, Wallet, Send } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import toast from 'react-hot-toast';
import api from '../api/axios';
import Pagination from '../components/Pagination';

const blankPayment = {
  id: '',
  customer_name: '',
  phone: '',
  amount: 0,
  payment_code: '',
  status: 'success',
  paid_at: '',
  provider: 'cash',
};

function toDate(value) {
  if (!value) return null;
  if (value._seconds) return new Date(value._seconds * 1000);
  if (value.seconds) return new Date(value.seconds * 1000);
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? null : date;
}

function formatKES(value) {
  return `Ksh ${Number(value || 0).toLocaleString('en-KE', { minimumFractionDigits: 2 })}`;
}

function formatDate(value) {
  const date = toDate(value);
  if (!date) return '-';
  return `${String(date.getDate()).padStart(2, '0')}.${String(date.getMonth() + 1).padStart(2, '0')}.${date.getFullYear()} ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
}

function disbursementLabel(payment) {
  const status = String(payment.tenant_settlement_status || '').toLowerCase();
  if (payment.provider === 'voucher') return 'Voucher';
  if (status === 'pending_withdrawal') return 'Available to withdraw';
  if (status === 'paystack_subaccount') return 'Tenant bank';
  if (status) return status.replaceAll('_', ' ');
  return 'Queued';
}

function sameDay(a, b) {
  return a && a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

function MetricCard({ title, value, helper }) {
  return (
    <div className="min-w-0 px-4 py-4 first:pl-5 last:pr-5" style={{ color: 'var(--app-text)' }}>
      <p className="text-[11px] font-medium uppercase tracking-wide text-[var(--app-muted)]">{title}</p>
      <p className="mt-2 truncate text-[22px] font-medium leading-tight tracking-tight">{formatKES(value)}</p>
      <p className="mt-2 text-xs font-normal text-[var(--app-muted)]">{helper}</p>
    </div>
  );
}

export default function Payments() {
  const [payments, setPayments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState('');
  const [tab, setTab] = useState('checked');
  const [modalOpen, setModalOpen] = useState(false);
  const [draft, setDraft] = useState(blankPayment);
  const [paymentSettings, setPaymentSettings] = useState({
    methods: ['daraja_paybill'],
    businessNumber: '',
    payoutPhone: '',
    bankCode: '',
    bankAccount: '',
    bankDarajaShortcode: '',
    settlementDestinationType: 'bank',
    darajaSettlementTillNumber: '',
    consumerKey: '',
    consumerSecret: '',
    hasConsumerKey: false,
    hasConsumerSecret: false,
    shortcode: '',
    passkey: '',
    hasPasskey: false,
    tillNumber: '',
    environment: 'production',
  });
  const [selectedMethod, setSelectedMethod] = useState('daraja_paybill');
  const [kenyanBanks, setKenyanBanks] = useState([]);
  const [savingMethods, setSavingMethods] = useState(false);
  const [methodsOpen, setMethodsOpen] = useState(false);
  const [verificationOpen, setVerificationOpen] = useState(false);
  const [verificationCode, setVerificationCode] = useState('');
  const [passwordFallback, setPasswordFallback] = useState(false);
  const [paymentChangeId, setPaymentChangeId] = useState('');
  const [settlementStatus, setSettlementStatus] = useState('not_created');
  const [withdrawalSummary, setWithdrawalSummary] = useState({ available_balance: '0', withdrawal_fee: '80', manual_payouts_enabled: false, withdrawals: [] });
  const [withdrawalOpen, setWithdrawalOpen] = useState(false);
  const [submittingWithdrawal, setSubmittingWithdrawal] = useState(false);
  const [withdrawalOtp, setWithdrawalOtp] = useState('');
  const [otpWithdrawalId, setOtpWithdrawalId] = useState('');
  const [withdrawalForm, setWithdrawalForm] = useState({ amount: '', payout_method: 'bank', destination_type: 'saved_bank', recipient_name: '', bankCode: '', bankAccount: '', phone: '' });
  const [page, setPage] = useState(1);
  const pageSize = 10;
  const onlineMethod = (method) => {
    if (method === 'paybill') return 'daraja_paybill';
    if (method === 'buygoods') return 'daraja_buygoods';
    return method;
  };

  async function loadPayments() {
    setLoading(true);
    try {
      const { data } = await api.get('/payments?page_size=100');
      setPayments(Array.isArray(data) ? data : data.results || []);
    } catch (error) {
      toast.error(error.response?.data?.message || 'Failed to load payments');
    } finally {
      setLoading(false);
    }
  }

  async function loadWithdrawals() {
    try {
      const { data } = await api.get('/payments/withdrawals');
      setWithdrawalSummary((current) => ({ ...current, ...data, withdrawals: data.withdrawals || [] }));
    } catch {
      // Paystack withdrawals are hidden when Daraja is the active provider.
    }
  }

  const paystackSelected = selectedMethod === 'paystack' || paymentSettings.methods.includes('paystack');

  const openWithdrawal = () => {
    setOtpWithdrawalId('');
    setWithdrawalOtp('');
    setWithdrawalForm((current) => ({
      ...current,
      amount: '',
      payout_method: paymentSettings.bankCode && paymentSettings.bankAccount ? 'bank' : 'mpesa',
      destination_type: paymentSettings.bankCode && paymentSettings.bankAccount ? 'saved_bank' : 'other_bank',
      recipient_name: paymentSettings.payoutPhone ? '' : '',
      bankCode: paymentSettings.bankCode,
      bankAccount: paymentSettings.bankAccount,
      phone: paymentSettings.payoutPhone,
    }));
    setWithdrawalOpen(true);
    loadWithdrawals();
  };

  const submitWithdrawal = async (event) => {
    event.preventDefault();
    const requestedAmount = Number(withdrawalForm.amount || 0);
    const availableBalance = Number(withdrawalSummary.available_balance || 0);
    const withdrawalFee = Number(withdrawalSummary.withdrawal_fee || 0);
    if (!Number.isFinite(requestedAmount) || requestedAmount <= 0 || requestedAmount + withdrawalFee > availableBalance) {
      toast.error('Not enough funds to withdraw. The amount and withdrawal fee must fit your available balance.');
      return;
    }
    setSubmittingWithdrawal(true);
    try {
      const payload = {
        amount: withdrawalForm.amount,
        payout_method: withdrawalForm.payout_method,
        destination_type: withdrawalForm.destination_type,
        recipient_name: withdrawalForm.recipient_name,
        bank_code: withdrawalForm.bankCode,
        account_number: withdrawalForm.bankAccount,
        phone: withdrawalForm.phone,
      };
      const { data } = await api.post('/payments/withdrawals', payload);
      if (data.otp_required) {
        setOtpWithdrawalId(data.withdrawal.id);
        toast('Enter the Paystack transfer OTP to continue.');
      } else {
        toast.success(data.message || 'Withdrawal submitted');
        setWithdrawalOpen(false);
      }
      loadWithdrawals();
    } catch (error) {
      toast.error(error.response?.data?.message || 'Could not submit withdrawal');
    } finally {
      setSubmittingWithdrawal(false);
    }
  };

  const submitWithdrawalOtp = async (event) => {
    event.preventDefault();
    setSubmittingWithdrawal(true);
    try {
      const { data } = await api.post(`/payments/withdrawals/${otpWithdrawalId}/otp`, { otp: withdrawalOtp });
      toast.success(data.message || 'Withdrawal submitted');
      setOtpWithdrawalId('');
      setWithdrawalOpen(false);
      loadWithdrawals();
    } catch (error) {
      toast.error(error.response?.data?.message || 'Could not verify transfer OTP');
    } finally {
      setSubmittingWithdrawal(false);
    }
  };

  useEffect(() => {
    loadPayments();
    loadWithdrawals();
    api.get('/settings/payment-banks').then(({ data }) => {
      setKenyanBanks(Array.isArray(data.results) ? data.results : []);
    }).catch((error) => {
      toast.error(error.response?.data?.message || 'Could not load the Kenyan bank list');
    });
    api.get('/settings/business').then(({ data }) => {
      setPaymentSettings({
      methods: data.payment_methods || ['daraja_paybill'],
      businessNumber: data.business_number || '',
      payoutPhone: data.payout_phone || '',
      bankCode: data.bank_code || '',
      bankAccount: data.bank_account_number || '',
      bankDarajaShortcode: data.bank_daraja_shortcode || '',
      settlementDestinationType: data.settlement_destination_type || 'bank',
      darajaSettlementTillNumber: data.daraja_settlement_till_number || '',
      consumerKey: '',
      consumerSecret: '',
      hasConsumerKey: Boolean(data.has_daraja_consumer_key),
      hasConsumerSecret: Boolean(data.has_daraja_consumer_secret),
      shortcode: data.daraja_shortcode || '',
      passkey: '',
      hasPasskey: Boolean(data.has_daraja_passkey),
      tillNumber: data.daraja_till_number || '',
      environment: data.daraja_environment || 'production',
      });
      const method = onlineMethod((data.payment_methods || [])[0]);
      const normalizedMethod = ['daraja_paybill', 'daraja_buygoods', 'paystack'].includes(method) ? method : 'daraja_paybill';
      setSelectedMethod(normalizedMethod);
      setSettlementStatus(normalizedMethod === 'paystack' ? (data.bank_account_status || data.paystack_settlement_status || data.settlement_status || 'missing_payout_details') : (data.daraja_b2b_settlement_status || 'missing_b2b_destination'));
    }).catch(() => {});
  }, []);

  const selectMethod = (method) => {
    const normalized = onlineMethod(method);
    setSelectedMethod(normalized);
    setPaymentSettings((current) => ({ ...current, methods: [normalized] }));
  };
  const savePaymentMethods = async () => {
    setSavingMethods(true);
    try {
      const { data: challenge } = await api.post('/settings/payment-change/request');
      setPasswordFallback(Boolean(challenge.password_fallback));
      setPaymentChangeId(challenge.challenge_id || '');
      setVerificationCode('');
      setVerificationOpen(true);
    } catch (error) {
      const responseMessage = error.response?.data?.message || error.response?.data?.error;
      toast.error(responseMessage || (error.response ? `Could not request verification (${error.response.status})` : error.message || 'Could not request verification'));
    } finally {
      setSavingMethods(false);
    }
  };

  const confirmPaymentMethods = async (event) => {
    event.preventDefault();
    if (!verificationCode.trim()) {
      toast.error(passwordFallback ? 'Enter your account password.' : 'Enter the verification code.');
      return;
    }
    setSavingMethods(true);
    try {
      const payload = {
        payment_methods: paymentSettings.methods.map(onlineMethod),
        business_number: paymentSettings.businessNumber,
        payout_phone: paymentSettings.payoutPhone,
        bank_code: paymentSettings.bankCode,
        bank_account_number: paymentSettings.bankAccount,
        bank_daraja_shortcode: paymentSettings.bankDarajaShortcode,
        settlement_destination_type: paymentSettings.settlementDestinationType,
        daraja_settlement_till_number: paymentSettings.darajaSettlementTillNumber,
        ...(paymentSettings.consumerKey ? { daraja_consumer_key: paymentSettings.consumerKey } : {}),
        ...(paymentSettings.consumerSecret ? { daraja_consumer_secret: paymentSettings.consumerSecret } : {}),
        daraja_shortcode: paymentSettings.shortcode,
        ...(paymentSettings.passkey ? { daraja_passkey: paymentSettings.passkey } : {}),
        daraja_till_number: paymentSettings.tillNumber,
        daraja_environment: paymentSettings.environment,
        daraja_shortcode_type: onlineMethod(selectedMethod) === 'daraja_buygoods' ? 'CustomerBuyGoodsOnline' : 'CustomerPayBillOnline',
        payment_provider: selectedMethod === 'paystack' ? 'paystack' : 'mpesa',
      };
      if (passwordFallback) {
        payload.current_password = verificationCode.trim();
      } else {
        payload.payment_change_id = paymentChangeId;
        payload.payment_change_code = verificationCode.trim();
      }
      const { data } = await api.patch('/settings/business', payload);
      setSettlementStatus(selectedMethod === 'paystack' ? (data.config?.bank_account_status || data.config?.paystack_settlement_status || data.config?.settlement_status || 'not_configured') : (data.config?.daraja_b2b_settlement_status || 'missing_b2b_destination'));
      toast.success('Payment settings saved');
      setVerificationOpen(false);
      setMethodsOpen(false);
    } catch (error) {
      const responseMessage = error.response?.data?.message || error.response?.data?.error;
      toast.error(responseMessage || (error.response ? `Failed to save payment methods (${error.response.status})` : error.message || 'Failed to save payment methods'));
    }
    finally { setSavingMethods(false); }
  };

  const successfulPayments = useMemo(() => payments.filter((payment) => payment.status === 'success'), [payments]);

  const rows = useMemo(() => {
    const base = tab === 'checked' ? successfulPayments : payments.filter((payment) => payment.status !== 'success');
    const needle = query.toLowerCase();
    return base.filter((payment) => `${payment.customer_name || ''} ${payment.access_username || ''} ${payment.phone || ''} ${payment.payment_code || ''} ${payment.daraja_receipt_number || ''}`.toLowerCase().includes(needle));
  }, [payments, query, successfulPayments, tab]);
  const pagedRows = rows.slice((page - 1) * pageSize, page * pageSize);

  useEffect(() => {
    setPage(1);
  }, [query, tab]);

  useEffect(() => {
    setPage((current) => Math.min(current, Math.max(1, Math.ceil(rows.length / pageSize))));
  }, [rows.length]);

  const totals = useMemo(() => {
    const now = new Date();
    const weekStart = new Date(now);
    weekStart.setDate(now.getDate() - now.getDay());
    weekStart.setHours(0, 0, 0, 0);
    const monthStart = new Date(now.getFullYear(), now.getMonth(), 1);
    const sumSince = (start) => successfulPayments.reduce((sum, payment) => {
      const date = toDate(payment.paid_at || payment.created_at || payment.initiated_at);
      return date && date >= start ? sum + Number(payment.amount || 0) : sum;
    }, 0);
    return {
      daily: successfulPayments.reduce((sum, payment) => (sameDay(toDate(payment.paid_at || payment.created_at || payment.initiated_at), now) ? sum + Number(payment.amount || 0) : sum), 0),
      weekly: sumSince(weekStart),
      monthly: sumSince(monthStart),
    };
  }, [successfulPayments]);

  const openRecordPayment = () => {
    setDraft({ ...blankPayment, paid_at: new Date().toISOString().slice(0, 16) });
    setModalOpen(true);
  };

  const savePayment = (event) => {
    event.preventDefault();
    const payload = {
      ...draft,
      id: draft.id || `PAY-${Date.now().toString().slice(-5)}`,
      amount: Number(draft.amount || 0),
      payment_code: draft.payment_code || `MANUAL-${Date.now().toString().slice(-6)}`,
    };
    setPayments((current) => [payload, ...current]);
    setModalOpen(false);
    setDraft(blankPayment);
    toast.success('Payment recorded locally');
  };

  return (
    <div className="space-y-7">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <h1 className="text-xl font-semibold text-black">Payments</h1>
          <span className="inline-flex h-5 w-5 items-center justify-center rounded-full border border-slate-900 text-[10px]">i</span>
        </div>
        <div className="flex gap-2"><button type="button" className="btn-secondary" onClick={() => setMethodsOpen(true)}><Settings2 size={14} />Payment methods</button>{paystackSelected && <button type="button" className="btn-secondary h-9 px-4" onClick={openWithdrawal}><Send size={14} />Withdraw</button>}<button type="button" className="btn-primary h-9 px-4 shadow-md" onClick={openRecordPayment}>
          <Coins size={14} />
          Record Payment
        </button></div>
      </div>

      <section className="grid grid-cols-1 overflow-hidden rounded-2xl border border-[var(--app-border)] bg-[var(--app-panel)] sm:grid-cols-2 xl:grid-cols-4 [&>div]:border-b [&>div]:border-[var(--app-border)] sm:[&>div:nth-child(odd)]:border-r xl:[&>div]:border-b-0 xl:[&>div:not(:last-child)]:border-r">
        <MetricCard title="Daily Earnings" value={totals.daily} helper="Total earnings today" />
        <MetricCard title="Weekly Earnings" value={totals.weekly} helper="Total earnings this week" />
        <MetricCard title="Monthly Earnings" value={totals.monthly} helper="Total earnings this month" />
        <MetricCard title="Mobile Money (This Month)" value={totals.monthly} helper="Excluding voucher payments" />
      </section>

      {methodsOpen && <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4"><section className="theme-card max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-lg border p-5 shadow-xl">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div><h2 className="page-title text-base">Payment methods</h2><p className="page-subtitle">Choose how customers pay. Saved tenant Daraja credentials are used automatically for Daraja collections. Platform-collected payments can be sent to a phone by B2C, or to a bank or till by B2B.</p></div>
          <button type="button" className="btn-secondary" onClick={() => setMethodsOpen(false)}>Close</button>
        </div>
        <select className="form-input mt-4" value={selectedMethod} onChange={(e) => selectMethod(e.target.value)}><option value="paybill">Paybill</option><option value="daraja_paybill">Paybill - Daraja API</option><option value="buygoods">Buy Goods</option><option value="daraja_buygoods">Buy Goods - Daraja API</option><option value="paystack">Bank account</option></select>
        {selectedMethod === 'paystack' && <div className="mt-4 grid gap-3 sm:grid-cols-2"><label className="form-label">Bank<select className="form-input" value={paymentSettings.bankCode} onChange={(e) => setPaymentSettings((c) => ({ ...c, bankCode: e.target.value }))}><option value="">Select a bank</option>{paymentSettings.bankCode && !kenyanBanks.some((bank) => bank.code === paymentSettings.bankCode) && <option value={paymentSettings.bankCode}>Saved bank (code {paymentSettings.bankCode})</option>}{kenyanBanks.map((bank) => <option key={`${bank.code}-${bank.name}`} value={bank.code}>{bank.name}</option>)}</select></label><label className="form-label">Bank code<input className="form-input" value={paymentSettings.bankCode} readOnly placeholder="Selected bank code" /></label><label className="form-label">Bank account number<input className="form-input" placeholder="Enter bank account number" value={paymentSettings.bankAccount} onChange={(e) => setPaymentSettings((c) => ({ ...c, bankAccount: e.target.value }))} /></label><label className="form-label">Paybill or business number<input className="form-input" placeholder="Enter Paybill or business number" value={paymentSettings.businessNumber} onChange={(e) => setPaymentSettings((c) => ({ ...c, businessNumber: e.target.value }))} /></label></div>}
        {selectedMethod === 'paystack' && <label className="form-label mt-3">Saved M-Pesa withdrawal number<input className="form-input" placeholder="2547XXXXXXXX" value={paymentSettings.payoutPhone} onChange={(e) => setPaymentSettings((c) => ({ ...c, payoutPhone: e.target.value }))} /></label>}
        {selectedMethod === 'paybill' && <div className="mt-4 grid gap-3 sm:grid-cols-2"><label className="form-label">Paybill number<input className="form-input" placeholder="Enter Paybill number" value={paymentSettings.businessNumber} onChange={(e) => setPaymentSettings((c) => ({ ...c, businessNumber: e.target.value }))} /></label><label className="form-label">Account number<input className="form-input" placeholder="Enter account number" value={paymentSettings.bankAccount} onChange={(e) => setPaymentSettings((c) => ({ ...c, bankAccount: e.target.value }))} /></label></div>}
        {selectedMethod === 'buygoods' && <div className="mt-4"><label className="form-label">Buy Goods till number<input className="form-input" placeholder="Enter Till number" value={paymentSettings.businessNumber} onChange={(e) => setPaymentSettings((c) => ({ ...c, businessNumber: e.target.value }))} /></label></div>}
        {selectedMethod === 'daraja_paybill' && <div className="mt-4 grid gap-3 sm:grid-cols-2"><input className="form-input" placeholder="Consumer key" value={paymentSettings.consumerKey} onChange={(e) => setPaymentSettings((c) => ({ ...c, consumerKey: e.target.value }))} /><input className="form-input" type="password" placeholder="Consumer secret" value={paymentSettings.consumerSecret} onChange={(e) => setPaymentSettings((c) => ({ ...c, consumerSecret: e.target.value }))} /><input className="form-input" placeholder="M-Pesa shortcode" value={paymentSettings.shortcode} onChange={(e) => setPaymentSettings((c) => ({ ...c, shortcode: e.target.value }))} /><input className="form-input" value="CustomerPayBillOnline" readOnly /><input className="form-input" type="password" placeholder="M-Pesa passkey" value={paymentSettings.passkey} onChange={(e) => setPaymentSettings((c) => ({ ...c, passkey: e.target.value }))} /><select className="form-input" value={paymentSettings.environment} onChange={(e) => setPaymentSettings((c) => ({ ...c, environment: e.target.value }))}><option value="production">Production</option><option value="sandbox">Sandbox</option></select></div>}
        {selectedMethod === 'daraja_buygoods' && <div className="mt-4 grid gap-3 sm:grid-cols-2"><input className="form-input" placeholder="Consumer key" value={paymentSettings.consumerKey} onChange={(e) => setPaymentSettings((c) => ({ ...c, consumerKey: e.target.value }))} /><input className="form-input" type="password" placeholder="Consumer secret" value={paymentSettings.consumerSecret} onChange={(e) => setPaymentSettings((c) => ({ ...c, consumerSecret: e.target.value }))} /><input className="form-input" type="password" placeholder="Passkey" value={paymentSettings.passkey} onChange={(e) => setPaymentSettings((c) => ({ ...c, passkey: e.target.value }))} /><input className="form-input" placeholder="M-Pesa shortcode" value={paymentSettings.shortcode} onChange={(e) => setPaymentSettings((c) => ({ ...c, shortcode: e.target.value }))} /><input className="form-input" value="CustomerBuyGoodsOnline" readOnly /><input className="form-input" placeholder="Buy Goods till number" value={paymentSettings.tillNumber} onChange={(e) => setPaymentSettings((c) => ({ ...c, tillNumber: e.target.value }))} /><select className="form-input" value={paymentSettings.environment} onChange={(e) => setPaymentSettings((c) => ({ ...c, environment: e.target.value }))}><option value="production">Production</option><option value="sandbox">Sandbox</option></select></div>}
        <div className="mt-4 rounded-md border border-[var(--app-border)] p-3">
          <h3 className="text-sm font-semibold">Automatic Daraja settlement destination</h3>
          <p className="mt-1 text-xs text-[var(--app-muted)]">Phone payouts use B2C. Bank accounts and tills use B2B. Safaricom must enable the matching product and shortcode permissions before live transfers.</p>
          <label className="form-label mt-3">Destination type<select className="form-input" value={paymentSettings.settlementDestinationType} onChange={(e) => setPaymentSettings((c) => ({ ...c, settlementDestinationType: e.target.value }))}><option value="phone">M-Pesa phone number (B2C)</option><option value="bank">Bank account via bank Paybill (B2B)</option><option value="till">Tenant Buy Goods till (B2B)</option></select></label>
          {paymentSettings.settlementDestinationType === 'phone' ? <label className="form-label mt-3">Tenant M-Pesa payout phone<input className="form-input" inputMode="tel" value={paymentSettings.payoutPhone} onChange={(e) => setPaymentSettings((c) => ({ ...c, payoutPhone: e.target.value }))} placeholder="2547XXXXXXXX" /></label> : paymentSettings.settlementDestinationType === 'bank' ? <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <label className="form-label">Bank M-Pesa Paybill shortcode<input className="form-input" inputMode="numeric" value={paymentSettings.bankDarajaShortcode} onChange={(e) => setPaymentSettings((c) => ({ ...c, bankDarajaShortcode: e.target.value }))} placeholder="Bank-provided Paybill shortcode" /></label>
            <label className="form-label">Bank account number<input className="form-input" value={paymentSettings.bankAccount} onChange={(e) => setPaymentSettings((c) => ({ ...c, bankAccount: e.target.value }))} placeholder="Account reference" /></label>
          </div> : <label className="form-label mt-3">Tenant Buy Goods till number<input className="form-input" inputMode="numeric" value={paymentSettings.darajaSettlementTillNumber} onChange={(e) => setPaymentSettings((c) => ({ ...c, darajaSettlementTillNumber: e.target.value }))} placeholder="Tenant till number" /></label>}
        </div>
        <div className="mt-5 flex justify-end"><button type="button" className="btn-primary" onClick={savePaymentMethods} disabled={savingMethods}>{savingMethods ? 'Saving...' : 'Save payment methods'}</button></div>
        <p className={`mt-3 text-xs font-semibold ${['active', 'ready', 'withdrawal_ready'].includes(settlementStatus) ? 'text-emerald-600' : 'text-amber-600'}`}>{selectedMethod === 'paystack' ? 'Withdrawal destination' : 'Payment settings'}: {['active', 'ready', 'withdrawal_ready'].includes(settlementStatus) ? 'Ready' : settlementStatus.replaceAll('_', ' ')}</p>
      </section></div>}

      {withdrawalOpen && <div className="fixed inset-0 z-[70] flex items-center justify-center bg-slate-950/60 p-4" role="presentation"><section role="dialog" aria-modal="true" aria-labelledby="withdrawal-title" className="theme-card max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-xl border p-5 shadow-xl">
        <div className="flex items-start justify-between gap-3"><div><h2 id="withdrawal-title" className="page-title text-base">Withdraw Paystack funds</h2><p className="page-subtitle mt-1">Available: {formatKES(withdrawalSummary.available_balance)}</p></div><button type="button" className="btn-secondary" onClick={() => { setWithdrawalOpen(false); setOtpWithdrawalId(''); }} aria-label="Close withdrawal dialog"><X size={16} /></button></div>
        {otpWithdrawalId ? <form onSubmit={submitWithdrawalOtp}>
          <p className="mt-4 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">Paystack requires an OTP to approve this transfer. Check the platform Paystack account phone.</p>
          <label className="form-label mt-4">Paystack transfer OTP<input autoFocus className="form-input" inputMode="numeric" autoComplete="one-time-code" value={withdrawalOtp} onChange={(event) => setWithdrawalOtp(event.target.value)} required /></label>
          <div className="mt-5 flex justify-end gap-2"><button type="button" className="btn-secondary" onClick={() => setWithdrawalOpen(false)} disabled={submittingWithdrawal}>Close</button><button type="submit" className="btn-primary" disabled={submittingWithdrawal}>{submittingWithdrawal ? 'Verifying...' : 'Verify and withdraw'}</button></div>
        </form> : <form onSubmit={submitWithdrawal}>
          <label className="form-label mt-4">Amount to send<input className="form-input" type="number" min="10" step="0.01" max={withdrawalForm.payout_method === 'mpesa' ? '250000' : undefined} value={withdrawalForm.amount} onChange={(event) => setWithdrawalForm((current) => ({ ...current, amount: event.target.value }))} required /></label>
          <p className="mt-2 text-xs text-[var(--app-muted)]">Available balance: {formatKES(withdrawalSummary.available_balance)}. A fee of {formatKES(withdrawalSummary.withdrawal_fee)} is also deducted.</p>
          {Number(withdrawalSummary.available_balance || 0) < Number(withdrawalSummary.withdrawal_fee || 0) && <p className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">Not enough funds to withdraw. Your available balance does not cover the withdrawal fee.</p>}
          <label className="form-label mt-4">Send to<select className="form-input" value={withdrawalForm.payout_method} onChange={(event) => setWithdrawalForm((current) => ({ ...current, payout_method: event.target.value, destination_type: event.target.value === 'bank' && current.bankCode && current.bankAccount ? 'saved_bank' : 'other_bank' }))}><option value="bank">Bank account</option><option value="mpesa">M-Pesa</option></select></label>
          <label className="form-label mt-4">Account / recipient name<input className="form-input" value={withdrawalForm.recipient_name} onChange={(event) => setWithdrawalForm((current) => ({ ...current, recipient_name: event.target.value }))} placeholder="Defaults to your business owner name" /></label>
          {withdrawalForm.payout_method === 'bank' && <>
            <label className="form-label mt-4">Bank destination<select className="form-input" value={withdrawalForm.destination_type} onChange={(event) => setWithdrawalForm((current) => ({ ...current, destination_type: event.target.value }))}><option value="other_bank">Enter another bank account</option>{paymentSettings.bankCode && paymentSettings.bankAccount && <option value="saved_bank">Use saved bank ••••{paymentSettings.bankAccount.slice(-4)}</option>}</select></label>
            {withdrawalForm.destination_type === 'saved_bank' ? <p className="mt-3 rounded-md border border-[var(--app-border)] px-3 py-2 text-xs text-[var(--app-text)]">Bank code {paymentSettings.bankCode} · account ••••{paymentSettings.bankAccount.slice(-4)}</p> : <div className="mt-3 grid gap-3 sm:grid-cols-2"><label className="form-label">Bank<select className="form-input" value={withdrawalForm.bankCode} onChange={(event) => setWithdrawalForm((current) => ({ ...current, bankCode: event.target.value }))} required><option value="">Select a bank</option>{kenyanBanks.map((bank) => <option key={`${bank.code}-${bank.name}`} value={bank.code}>{bank.name}</option>)}</select></label><label className="form-label">Account number<input className="form-input" value={withdrawalForm.bankAccount} onChange={(event) => setWithdrawalForm((current) => ({ ...current, bankAccount: event.target.value }))} required /></label></div>}
          </>}
          {withdrawalForm.payout_method === 'mpesa' && <label className="form-label mt-4">M-Pesa phone number<input className="form-input" inputMode="tel" value={withdrawalForm.phone} onChange={(event) => setWithdrawalForm((current) => ({ ...current, phone: event.target.value }))} placeholder="2547XXXXXXXX" required /></label>}
          <div className="mt-5 flex justify-end gap-2"><button type="button" className="btn-secondary" onClick={() => setWithdrawalOpen(false)} disabled={submittingWithdrawal}>Cancel</button><button type="submit" className="btn-primary" disabled={submittingWithdrawal}>{submittingWithdrawal ? 'Submitting...' : 'Withdraw funds'}</button></div>
        </form>}
      </section></div>}

      {verificationOpen && <div className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-950/50 p-4" role="presentation"><section role="dialog" aria-modal="true" aria-labelledby="payment-verification-title" className="theme-card w-full max-w-md rounded-lg border p-5 shadow-xl">
        <div className="flex items-start justify-between gap-3"><div><h2 id="payment-verification-title" className="page-title text-base">Verify payment changes</h2><p className="page-subtitle mt-1">{passwordFallback ? 'Code delivery failed. Enter your account password to confirm this change.' : 'Enter the verification code sent to your tenant phone or email.'}</p></div><button type="button" className="btn-secondary" onClick={() => setVerificationOpen(false)} aria-label="Close verification dialog"><X size={16} /></button></div>
        <form onSubmit={confirmPaymentMethods}>
          <label className="form-label mt-4">{passwordFallback ? 'Account password' : 'Verification code'}<input autoFocus className="form-input" type={passwordFallback ? 'password' : 'text'} inputMode={passwordFallback ? undefined : 'numeric'} autoComplete={passwordFallback ? 'current-password' : 'one-time-code'} value={verificationCode} onChange={(event) => setVerificationCode(event.target.value)} placeholder={passwordFallback ? 'Enter account password' : 'Enter verification code'} /></label>
          <div className="mt-5 flex justify-end gap-2"><button type="button" className="btn-secondary" onClick={() => setVerificationOpen(false)} disabled={savingMethods}>Cancel</button><button type="submit" className="btn-primary" disabled={savingMethods}>{savingMethods ? 'Verifying...' : 'Verify and save'}</button></div>
        </form>
      </section></div>}

      <section className="border-b border-slate-200">
        <div className="flex gap-6">
          {[
            ['checked', 'Checked payments', CheckCheck],
            ['unchecked', 'Unchecked payments', X],
          ].map(([key, label, Icon]) => (
            <button key={key} type="button" className={`inline-flex h-10 items-center gap-2 border-b-2 text-xs font-medium ${tab === key ? 'border-[var(--app-accent)] text-[var(--app-accent)]' : 'border-transparent text-slate-500'}`} onClick={() => setTab(key)}>
              <Icon size={15} />
              {label}
            </button>
          ))}
        </div>
      </section>

      <section className="overflow-hidden rounded-lg border border-slate-200 bg-white">
        <div className="flex justify-end border-b border-slate-200 p-3">
          <label className="relative block w-full max-w-xs">
            
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input className="form-input mt-0 h-9 pl-9" placeholder="Search" value={query} onChange={(event) => setQuery(event.target.value)} />
          </label>
        </div>

        <div className="overflow-x-auto">
          <table className="min-w-[980px] w-full">
            <thead className="bg-slate-50 text-left text-xs font-semibold text-black">
              <tr>
                <th className="w-12 px-5 py-4"><input type="checkbox" className="h-4 w-4 rounded border-slate-300" /></th>
                {['User', 'Phone', 'Receipt No.', 'Amount', 'Checked', 'Paid At', 'Disbursement'].map((heading) => (
                  <th key={heading} className="px-5 py-4">
                    <span className="inline-flex items-center gap-1">{heading}<ChevronDown size={15} className="text-slate-400" /></span>
                  </th>
                ))}
                <th className="px-5 py-4" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 text-xs text-black">
              {loading ? (
                <tr><td className="px-5 py-10 text-center text-slate-500" colSpan="9">Loading payments...</td></tr>
              ) : rows.length === 0 ? (
                <tr><td className="px-5 py-10 text-center text-slate-500" colSpan="9">No payments found.</td></tr>
              ) : pagedRows.map((payment) => (
                <tr key={payment.id}>
                  <td className="px-5 py-4"><input type="checkbox" className="h-4 w-4 rounded border-slate-300" /></td>
                  <td className="px-5 py-4 font-bold" style={{ color: 'var(--app-accent)' }}>{payment.customer_name || payment.access_username || '-'}</td>
                  <td className="px-5 py-4">{payment.phone || '-'}</td>
                  <td className="px-5 py-4">{payment.payment_code || payment.daraja_receipt_number || '-'}</td>
                  <td className="px-5 py-4">{formatKES(payment.amount)}</td>
                  <td className="px-5 py-4"><span className="rounded-md border border-emerald-200 bg-emerald-50 px-2 py-1 text-[10px] text-emerald-700">{payment.status === 'success' ? 'Yes' : 'No'}</span></td>
                  <td className="px-5 py-4">{formatDate(payment.paid_at || payment.created_at || payment.initiated_at)}</td>
                  <td className="px-5 py-4"><span className="rounded-md border px-2 py-1 text-[10px]" style={{ borderColor: 'var(--app-accent-soft)', background: 'var(--app-accent-muted)', color: 'var(--app-accent)' }}>{disbursementLabel(payment)}</span></td>
                  <td className="px-5 py-4 text-right" style={{ color: 'var(--app-accent)' }}><MoreVertical size={16} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Pagination page={page} pageSize={pageSize} total={rows.length} label="payments" onPageChange={setPage} />
      </section>

      {modalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4">
          <form className="w-full max-w-lg rounded-lg bg-white p-5 shadow-xl" onSubmit={savePayment}>
            <h2 className="text-base font-semibold text-black">Record Payment</h2>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <label className="text-xs font-semibold text-slate-600">User<input className="form-input" value={draft.customer_name} onChange={(event) => setDraft((current) => ({ ...current, customer_name: event.target.value }))} required /></label>
              <label className="text-xs font-semibold text-slate-600">Phone<input className="form-input" value={draft.phone} onChange={(event) => setDraft((current) => ({ ...current, phone: event.target.value }))} /></label>
              <label className="text-xs font-semibold text-slate-600">Receipt No.<input className="form-input" value={draft.payment_code} onChange={(event) => setDraft((current) => ({ ...current, payment_code: event.target.value }))} /></label>
              <label className="text-xs font-semibold text-slate-600">Amount<input className="form-input" type="number" value={draft.amount} onChange={(event) => setDraft((current) => ({ ...current, amount: event.target.value }))} required /></label>
              <label className="text-xs font-semibold text-slate-600">Paid At<input className="form-input" type="datetime-local" value={draft.paid_at} onChange={(event) => setDraft((current) => ({ ...current, paid_at: event.target.value }))} /></label>
              <label className="text-xs font-semibold text-slate-600">Status<select className="form-input" value={draft.status} onChange={(event) => setDraft((current) => ({ ...current, status: event.target.value }))}><option value="success">Checked</option><option value="pending">Unchecked</option><option value="failed">Failed</option></select></label>
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <button type="button" className="btn-secondary" onClick={() => setModalOpen(false)}>Cancel</button>
              <button type="submit" className="btn-primary">
                <Plus size={14} />
                Save Payment
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
