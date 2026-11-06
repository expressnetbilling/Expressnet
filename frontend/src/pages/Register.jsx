import { useState } from 'react';
import toast from 'react-hot-toast';
import { CheckCircle2, Eye, EyeOff } from 'lucide-react';
import api from '../api/axios';
import { appLoginUrl } from '../config/hostRouting';

const initialForm = { business_name: '', owner_name: '', email: '', phone: '', password: '', confirm_password: '' };
const labels = { business_name: 'Name of your business', owner_name: 'Name', email: 'Email', phone: 'Phone', password: 'Password', confirm_password: 'Confirm password' };
const trialDays = import.meta.env.VITE_TENANT_TRIAL_DAYS || '14';

function Field({ name, type = 'text', value, error, onChange, showPassword, onTogglePassword }) {
  const passwordField = name === 'password' || name === 'confirm_password';
  return (
    <div>
      <label className="mb-2 block text-xs font-medium text-slate-300" htmlFor={name}>{labels[name]}</label>
      <div className="relative">
        <input id={name} name={name} type={passwordField ? (showPassword ? 'text' : 'password') : type} className="h-12 w-full rounded-xl border border-white/10 bg-slate-900/80 px-4 pr-12 text-sm text-white outline-none transition placeholder:text-slate-500 focus:border-cyan-400 focus:ring-4 focus:ring-cyan-400/10" value={value} onChange={onChange} autoComplete={name === 'password' || name === 'confirm_password' ? 'new-password' : name === 'email' ? 'email' : 'on'} />
        {passwordField && <button type="button" onClick={onTogglePassword} className="absolute inset-y-0 right-0 flex w-12 items-center justify-center text-slate-400 transition hover:text-white" aria-label={showPassword ? `Hide ${labels[name].toLowerCase()}` : `Show ${labels[name].toLowerCase()}`}><span className="sr-only">{showPassword ? 'Hide' : 'Show'} {labels[name].toLowerCase()}</span>{showPassword ? <EyeOff size={17} /> : <Eye size={17} />}</button>}
      </div>
      {error && <p className="mt-1.5 text-xs text-rose-400">{error}</p>}
    </div>
  );
}

export default function Register() {
  const [form, setForm] = useState(initialForm);
  const [errors, setErrors] = useState({});
  const [loading, setLoading] = useState(false);
  const [registration, setRegistration] = useState(null);
  const [visiblePasswords, setVisiblePasswords] = useState({ password: false, confirm_password: false });

  const registrationNotice = new URLSearchParams(window.location.search).get('verification');

  const update = (event) => {
    setForm((current) => ({ ...current, [event.target.name]: event.target.value }));
    setErrors((current) => ({ ...current, [event.target.name]: '' }));
  };

  const validate = () => {
    const nextErrors = {};
    Object.entries(form).forEach(([key, value]) => { if (!String(value).trim()) nextErrors[key] = `${labels[key]} is required`; });
    if (form.password && form.password.length < 6) nextErrors.password = 'Password must be at least 6 characters';
    if (form.confirm_password && form.password !== form.confirm_password) nextErrors.confirm_password = 'Passwords do not match';
    setErrors(nextErrors);
    return Object.keys(nextErrors).length === 0;
  };

  const submit = async (event) => {
    event.preventDefault();
    if (!validate()) return;
    setLoading(true);
    try {
      const { confirm_password, ...payload } = form;
      const { data } = await api.post('/auth/register', payload);
      setRegistration({ message: data.message || 'Your account was created. Check your email and open the verification link to continue to sign in.', email: form.email });
    } catch (error) {
      const responseMessage = error.response?.data?.message || error.response?.data?.error || error.message || '';
      const isInternalFailure = Number(error.response?.status || 0) >= 500
        || /database|schema|migration|integrity|traceback/i.test(responseMessage);
      const message = isInternalFailure
        ? 'We could not create your account right now. Please try again shortly.'
        : (responseMessage || 'Registration failed');
      toast.error(message);
    } finally { setLoading(false); }
  };

  return (
    <main className="relative flex min-h-screen items-center justify-center overflow-hidden bg-[#080d18] px-4 py-8 text-white sm:px-6 sm:py-12">
      <div aria-hidden="true" className="pointer-events-none absolute -left-32 -top-32 h-80 w-80 rounded-full bg-cyan-500/10 blur-3xl" />
      <div aria-hidden="true" className="pointer-events-none absolute -bottom-40 -right-24 h-96 w-96 rounded-full bg-blue-600/10 blur-3xl" />
      <section className="relative w-full max-w-2xl rounded-2xl border border-white/10 bg-slate-900/90 p-5 shadow-2xl shadow-black/40 sm:p-8 md:p-10">
        <header className="mb-7 sm:mb-8">
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-cyan-400">Expressnetbilling</p>
          <h1 className="mt-2 text-2xl font-bold tracking-tight text-white sm:text-3xl">Register your hotspot business</h1>
          <p className="mt-3 max-w-xl text-sm leading-6 text-slate-400">Create your tenant account and billing workspace. New tenants get a {trialDays}-day grace period before system payment is required.</p>
        </header>

        {registrationNotice && <div className="mb-6 rounded-xl border border-amber-400/20 bg-amber-400/10 px-4 py-3 text-sm leading-6 text-amber-100">{registrationNotice === 'invalid' ? 'That verification link is invalid or has expired. Contact support for a new link.' : 'Your verification link could not be read. Contact support for help.'}</div>}

        <form className="space-y-7" onSubmit={submit}>
          <div>
            <h2 className="mb-4 text-sm font-semibold text-white">Business and account details</h2>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field name="business_name" value={form.business_name} error={errors.business_name} onChange={update} />
              <Field name="owner_name" value={form.owner_name} error={errors.owner_name} onChange={update} />
              <Field name="email" type="email" value={form.email} error={errors.email} onChange={update} />
              <Field name="phone" type="tel" value={form.phone} error={errors.phone} onChange={update} />
              <Field name="password" value={form.password} error={errors.password} onChange={update} showPassword={visiblePasswords.password} onTogglePassword={() => setVisiblePasswords((current) => ({ ...current, password: !current.password }))} />
              <Field name="confirm_password" value={form.confirm_password} error={errors.confirm_password} onChange={update} showPassword={visiblePasswords.confirm_password} onTogglePassword={() => setVisiblePasswords((current) => ({ ...current, confirm_password: !current.confirm_password }))} />
            </div>
          </div>
          <div className="flex flex-col-reverse gap-4 border-t border-white/10 pt-5 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-sm text-slate-400">Already registered? <a className="font-semibold text-cyan-400 hover:text-cyan-300" href={appLoginUrl()}>Login</a></p>
            <button type="submit" className="inline-flex h-12 w-full items-center justify-center rounded-xl bg-cyan-500 px-6 text-sm font-semibold text-slate-950 transition hover:bg-cyan-400 disabled:cursor-not-allowed disabled:opacity-60 sm:w-auto" disabled={loading}>{loading ? 'Creating account…' : 'Create account'}</button>
          </div>
        </form>
      </section>

      {registration && <div className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-black/75 p-4 backdrop-blur-sm" role="presentation">
        <section role="dialog" aria-modal="true" aria-labelledby="registration-success-title" className="relative my-auto w-full max-w-md rounded-2xl border border-white/10 bg-slate-900 p-6 shadow-2xl shadow-black/50 sm:p-8">
          <CheckCircle2 size={38} className="text-emerald-400" />
          <h2 id="registration-success-title" className="mt-4 text-xl font-semibold text-white">Registration successful</h2>
          <p className="mt-2 text-sm leading-6 text-slate-300">{registration.message}</p>
          <p className="mt-4 rounded-xl border border-white/10 bg-slate-950/70 px-4 py-3 text-sm text-slate-300">Email sent to <span className="font-medium text-white">{registration.email}</span></p>
          <button type="button" className="mt-6 h-11 w-full rounded-xl bg-cyan-500 text-sm font-semibold text-slate-950 transition hover:bg-cyan-400" onClick={() => { window.location.href = '/'; }}>OK</button>
        </section>
      </div>}
    </main>
  );
}
