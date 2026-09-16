import { Eye, EyeOff, Shield } from 'lucide-react';
import { useState } from 'react';
import toast from 'react-hot-toast';
import { useLocation, useNavigate } from 'react-router-dom';
import adminApi from '../../api/adminAxios';
import { useAdminAuth } from '../../context/AdminAuthContext';
import { ADMIN_DASHBOARD_PATH } from '../../config/adminPaths';

export default function AdminLogin() {
  const navigate = useNavigate();
  const location = useLocation();
  const { loginAdmin } = useAdminAuth();
  const [form, setForm] = useState({ email: '', password: '' });
  const [errors, setErrors] = useState({});
  const [loading, setLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  const update = (event) => {
    setForm((current) => ({ ...current, [event.target.name]: event.target.value }));
    setErrors((current) => ({ ...current, [event.target.name]: '' }));
  };

  const submit = async (event) => {
    event.preventDefault();
    const nextErrors = {};
    if (!form.email.trim()) nextErrors.email = 'Email is required';
    if (!form.password) nextErrors.password = 'Password is required';
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) return;

    setLoading(true);
    try {
      const { data } = await adminApi.post('/admin/auth/login', form);
      loginAdmin(data.token, data.admin);
      toast.success('Admin session started');
      navigate(location.state?.from?.pathname || ADMIN_DASHBOARD_PATH, { replace: true });
    } catch (error) {
      toast.error(error.response?.data?.error || error.response?.data?.message || error.message || 'Admin login failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="flex min-h-screen items-center justify-center bg-[#1a1a2e] px-4 py-10">
      <section className="w-full max-w-md rounded-lg border border-[#e94560]/30 bg-[#16213e] p-8 text-white shadow-2xl">
        <div className="mb-8 flex items-center gap-4">
          <div className="flex h-12 w-12 items-center justify-center rounded-md bg-[#e94560]">
            <Shield size={26} />
          </div>
          <div>
            <p className="text-xs font-medium uppercase tracking-wide text-[#e94560]">Admin Portal</p>
            <h1 className="text-2xl font-semibold tracking-tight">Secure Sign In</h1>
          </div>
        </div>

        <form className="space-y-5" onSubmit={submit}>
          <div>
            <label className="block text-xs font-medium uppercase tracking-wide text-slate-300" htmlFor="email">Email</label>
            <input id="email" name="email" type="email" className="mt-1 h-8 w-full rounded-md border border-slate-600 bg-[#1a1a2e] px-3 text-xs outline-none focus:border-[#e94560] focus:ring-2 focus:ring-[#e94560]/20" value={form.email} onChange={update} />
            {errors.email && <p className="mt-1 text-xs font-medium text-red-300">{errors.email}</p>}
          </div>

          <div>
            <label className="block text-xs font-medium uppercase tracking-wide text-slate-300" htmlFor="password">Password</label>
            <div className="relative">
              <input
                id="password"
                name="password"
                type={showPassword ? 'text' : 'password'}
                className="mt-1 h-8 w-full rounded-md border border-slate-600 bg-[#1a1a2e] px-3 pr-11 text-xs outline-none focus:border-[#e94560] focus:ring-2 focus:ring-[#e94560]/20"
                value={form.password}
                onChange={update}
              />
              <button
                type="button"
                className="absolute right-2 top-1/2 inline-flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-md text-slate-300 transition hover:bg-white/10 hover:text-white focus:outline-none focus:ring-2 focus:ring-[#e94560]/30"
                aria-label={showPassword ? 'Hide password' : 'Show password'}
                onClick={() => setShowPassword((current) => !current)}
              >
                {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
              </button>
            </div>
            {errors.password && <p className="mt-1 text-xs font-medium text-red-300">{errors.password}</p>}
          </div>

          <button type="submit" className="inline-flex h-8 w-full items-center justify-center gap-2 rounded-md bg-[#e94560] px-4 text-xs font-medium text-white transition hover:bg-[#c73652] disabled:opacity-60" disabled={loading}>
            {loading ? 'Verifying...' : 'Login as Admin'}
          </button>
        </form>
      </section>
    </main>
  );
}
