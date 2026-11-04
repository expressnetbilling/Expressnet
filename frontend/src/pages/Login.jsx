import { useState } from 'react';
import { Eye, EyeOff } from 'lucide-react';
import toast from 'react-hot-toast';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import api from '../api/axios';
import { useAuth } from '../context/AuthContext';
import { applyTenantTheme, getStoredTenantSettings, TENANT_THEME_EVENT } from '../utils/theme';
import { useEffect } from 'react';

function getMessage(error) {
  return error.response?.data?.message || error.message || 'Something went wrong. Please try again.';
}

export default function Login() {
  const navigate = useNavigate();
  const location = useLocation();
  const { login } = useAuth();
  const [loading, setLoading] = useState(false);
  const [form, setForm] = useState({ email: '', password: '' });
  const [errors, setErrors] = useState({});
  const [showPassword, setShowPassword] = useState(false);
  const [tenantTheme, setTenantTheme] = useState(() => getStoredTenantSettings());
  const emailVerified = new URLSearchParams(location.search).get('email_verified') === '1';
  const verificationError = new URLSearchParams(location.search).get('verification');

  useEffect(() => {
    const updateTheme = (event) => setTenantTheme(applyTenantTheme(event?.detail || getStoredTenantSettings()));
    updateTheme();
    window.addEventListener(TENANT_THEME_EVENT, updateTheme);
    window.addEventListener('storage', updateTheme);
    return () => {
      window.removeEventListener(TENANT_THEME_EVENT, updateTheme);
      window.removeEventListener('storage', updateTheme);
    };
  }, []);

  const update = (event) => {
    setForm((current) => ({ ...current, [event.target.name]: event.target.value }));
    setErrors((current) => ({ ...current, [event.target.name]: '' }));
  };

  const validate = () => {
    const nextErrors = {};
    if (!form.email.trim()) nextErrors.email = 'Email is required';
    if (!form.password) nextErrors.password = 'Password is required';
    setErrors(nextErrors);
    return Object.keys(nextErrors).length === 0;
  };

  const submit = async (event) => {
    event.preventDefault();
    if (!validate()) return;

    setLoading(true);
    try {
      const { data } = await api.post('/auth/login', form);
      login(data.token, data.tenant);
      toast.success('Welcome back');
      navigate(location.state?.from?.pathname || '/dashboard', { replace: true });
    } catch (error) {
      toast.error(getMessage(error));
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="theme-page flex min-h-screen items-center justify-center px-4 py-8 sm:py-10">
      <section className="theme-card w-full max-w-md rounded-2xl border p-7 shadow-2xl sm:p-10" style={{ borderColor: 'var(--app-border)', boxShadow: '0 24px 70px rgb(0 0 0 / 28%)' }}>
        <div className="mb-9">
          <p className="text-sm font-semibold uppercase tracking-wide text-app-accent">{tenantTheme.business_name || 'Expressnetbilling'}</p>
          <h1 className="theme-text mt-2 text-2xl font-bold">Sign in to your account</h1>
          {emailVerified && <p className="mt-3 rounded-xl border border-emerald-500/20 bg-emerald-500/10 px-3 py-2 text-xs font-medium text-emerald-500">Your email is verified. Sign in to continue.</p>}
          {verificationError && <p className="mt-3 rounded-xl border border-amber-500/20 bg-amber-500/10 px-3 py-2 text-xs font-medium text-amber-500">{verificationError === 'invalid' ? 'That verification link is invalid or has expired. Contact support for a new link.' : 'We could not read the verification link. Contact support for help.'}</p>}
        </div>

        <form className="space-y-6" onSubmit={submit}>
          <div>
            <label className="form-label" htmlFor="email">Email</label>
            <input id="email" name="email" type="email" className="form-input mt-2 h-12 rounded-xl px-4 text-sm" value={form.email} onChange={update} />
            {errors.email && <p className="form-error">{errors.email}</p>}
          </div>

          <div>
            <label className="form-label" htmlFor="password">Password</label>
            <div className="relative">
              <input
                id="password"
                name="password"
                type={showPassword ? 'text' : 'password'}
                className="form-input mt-2 h-12 rounded-xl px-4 pr-12 text-sm"
                value={form.password}
                onChange={update}
              />
              <button
                type="button"
                className="absolute right-2 top-[calc(50%+0.25rem)] inline-flex h-9 w-9 -translate-y-1/2 items-center justify-center rounded-lg text-slate-500 transition hover:bg-slate-100 hover:text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-100 dark:text-slate-300 dark:hover:bg-slate-700 dark:hover:text-white"
                aria-label={showPassword ? 'Hide password' : 'Show password'}
                onClick={() => setShowPassword((current) => !current)}
              >
                {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
              </button>
            </div>
            {errors.password && <p className="form-error">{errors.password}</p>}
          </div>

          <button type="submit" className="btn-primary h-11 w-full rounded-xl text-sm" disabled={loading}>
            {loading ? 'Signing in...' : 'Login'}
          </button>
        </form>

        <p className="mt-6 text-center text-sm text-slate-600">
          Don't have an account?{' '}
          <Link className="font-semibold text-app-accent hover:opacity-80" to="/register">
            Create an account
          </Link>
        </p>
      </section>
    </main>
  );
}
