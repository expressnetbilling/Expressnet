import {
  ArrowRight,
  CheckCircle2,
  Clipboard,
  EthernetPort,
  PlugZap,
  RefreshCw,
  Router,
  Wifi,
} from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import toast from 'react-hot-toast';
import api from '../api/axios';

function portLabel(name) {
  return String(name || '')
    .replace(/^ether\s*(\d+)$/i, 'Ether $1')
    .replace(/^ether(\d+)$/i, 'Ether $1')
    .replace(/^wlan\s*(\d+)$/i, 'Wlan $1')
    .replace(/^wlan(\d+)$/i, 'Wlan $1')
    .replace(/^wifi\s*(\d+)$/i, 'Wifi $1')
    .replace(/^wifi(\d+)$/i, 'Wifi $1');
}

function serviceLabel(service) {
  if (service === 'pppoe') return 'PPPoE';
  if (service === 'hotspot') return 'Hotspot';
  if (service === 'both') return 'PPPoE + Hotspot';
  return String(service || '').toUpperCase();
}

export default function MikrotikSettings() {
  const [provisioningState, setProvisioningState] = useState(null);
  const [loading, setLoading] = useState(true);
  const [provision, setProvision] = useState(null);
  const [routerStatus, setRouterStatus] = useState(null);
  const [migrationSummary, setMigrationSummary] = useState(null);
  const [pullingStatus, setPullingStatus] = useState(false);
  const [assigning, setAssigning] = useState(false);
  const [activeStep, setActiveStep] = useState('link');
  const [selectedServices, setSelectedServices] = useState(['hotspot']);
  const [selectedPorts, setSelectedPorts] = useState([]);
  const [routerName, setRouterName] = useState('');
  const [migrationMode, setMigrationMode] = useState(false);
  const provisionRequestRef = useRef({ key: '', promise: null, data: null });

  const configured = useMemo(
    () => Boolean(
      provisioningState?.lastSeenAt
      || provisioningState?.status === 'completed'
      || provisioningState?.status === 'script_downloaded',
    ),
    [provisioningState],
  );

  const isReprovisioning = useMemo(() => new URLSearchParams(window.location.search).get('reprovision') === '1', []);
  const isAddingRouter = useMemo(() => new URLSearchParams(window.location.search).get('add') === '1', []);
  const showProvisioning = !configured || isReprovisioning || isAddingRouter;

  const selectedService = useMemo(() => {
    if (selectedServices.includes('pppoe') && selectedServices.includes('hotspot')) return 'both';
    return selectedServices[0] || '';
  }, [selectedServices]);
  const selectablePorts = (routerStatus?.interfaces || [])
    .filter((item) => item.customer_assignable !== false)
    .map((item) => item.name);
  const allSelectablePortsSelected = selectablePorts.length > 0
    && selectablePorts.every((portName) => selectedPorts.includes(portName));

  const pullRouterStatus = async (options = {}) => {
    setPullingStatus(true);
    try {
      const { data } = await api.get('/router/status');
      setRouterStatus(data);
      if (!options.silent) {
        const fromSnapshot = data.source === 'provisioning_snapshot' || data.source === 'provisioning_seen';
        toast.success(fromSnapshot ? 'Loaded router provisioning state' : 'Router status pulled');
      }
      return data;
    } catch (error) {
      toast.error(error.response?.data?.message || 'Failed to pull router status');
      return null;
    } finally {
      setPullingStatus(false);
    }
  };

  async function loadConfig() {
    setLoading(true);
    try {
      const { data } = await api.get('/settings/mikrotik');
      if (isAddingRouter) {
        // Adding a router is an isolated provisioning session. Do not expose
        // the previously linked router's snapshot or status in this screen.
        setProvisioningState({ status: '', provisionedAt: '', lastSeenAt: '', lastSeenIp: '', identity: '', version: '', board: '' });
        setRouterStatus(null);
        setMigrationSummary(null);
        setRouterName('');
        setActiveStep('link');
        return;
      }
      const nextProvisioningState = {
        status: data.mikrotik_provisioning_status || '',
        provisionedAt: data.mikrotik_provisioned_at || '',
        lastSeenAt: data.mikrotik_last_seen_at || '',
        lastSeenIp: data.mikrotik_last_seen_ip || '',
        identity: data.mikrotik_detected_identity || '',
        version: data.mikrotik_detected_version || '',
        board: data.mikrotik_detected_board || '',
      };
      setMigrationSummary(data.mikrotik_migration_import_summary || null);
      setRouterName(data.mikrotik_name || data.router_name || data.mikrotik_detected_identity || '');
      setProvisioningState({
        ...nextProvisioningState,
      });
      const nextConfigured = Boolean(
        nextProvisioningState.lastSeenAt
        || nextProvisioningState.status === 'completed'
        || nextProvisioningState.status === 'script_downloaded',
      );
      setActiveStep((current) => {
        if (current === 'configure') return current;
        return nextConfigured && !isReprovisioning ? 'configure' : 'link';
      });
      if (!isAddingRouter && (data.mikrotik_last_seen_at || data.mikrotik_provisioning_status === 'completed')) {
        pullRouterStatus({ silent: true });
      }
    } catch (error) {
      toast.error(error.response?.data?.message || 'Failed to load MikroTik settings');
    } finally {
      setLoading(false);
    }
  }

  async function loadProvisionCommand() {
    const params = new URLSearchParams();
    if (isAddingRouter) params.set('fresh', '1');
    if (migrationMode) params.set('migrate', '1');
    const name = routerName.trim();
    if (name) params.set('name', name);
    const query = params.toString();
    const requestKey = query || 'default';
    const previous = provisionRequestRef.current;
    if (previous.key === requestKey) {
      if (previous.data) {
        setProvision(previous.data);
        return previous.data;
      }
      if (previous.promise) return previous.promise;
    }

    const request = api.get(`/router/provision-command${query ? `?${query}` : ''}`)
      .then(({ data }) => {
        provisionRequestRef.current = { key: requestKey, promise: null, data };
        setProvision(data);
        return data;
      })
      .catch((error) => {
        if (provisionRequestRef.current.key === requestKey) {
          provisionRequestRef.current = { key: '', promise: null, data: null };
          toast.error(error.response?.data?.message || 'Failed to create provisioning command');
        }
        return null;
      });
    provisionRequestRef.current = { key: requestKey, promise: request, data: null };
    try {
      return await request;
    } catch {
      return null;
    }
  }

  useEffect(() => {
    loadConfig();
    loadProvisionCommand();
  }, []);

  useEffect(() => {
    loadProvisionCommand();
  }, [migrationMode]);

  const copy = async (value, label) => {
    try {
      await navigator.clipboard.writeText(value || '');
      toast.success(`${label} copied`);
    } catch {
      toast.error('Copy failed');
    }
  };

  const goToConfiguration = async () => {
    const data = await pullRouterStatus();
    if (data) setActiveStep('configure');
  };

  const togglePort = (portName) => {
    const port = (routerStatus?.interfaces || []).find((item) => item.name === portName);
    if (port && port.customer_assignable === false) {
      toast.error(`${portLabel(portName)} is the WAN/uplink port. Choose a customer LAN port.`);
      return;
    }
    setSelectedPorts((current) => (
      current.includes(portName)
        ? current.filter((name) => name !== portName)
        : [...current, portName]
    ));
  };

  const toggleService = (service) => {
    setSelectedServices((current) => {
      if (current.includes(service)) {
        return current.length === 1 ? current : current.filter((item) => item !== service);
      }
      const order = ['pppoe', 'hotspot'];
      return [...current, service].sort((a, b) => order.indexOf(a) - order.indexOf(b));
    });
  };

  const toggleAllPorts = () => {
    setSelectedPorts((current) => (
      allSelectablePortsSelected
        ? current.filter((portName) => !selectablePorts.includes(portName))
        : [...new Set([...current, ...selectablePorts])]
    ));
  };

  const assignPorts = async () => {
    if (!selectedService) {
      toast.error('Select PPPoE, Hotspot, or both');
      return;
    }
    if (selectedPorts.length === 0) {
      toast.error('Select at least one router port');
      return;
    }
    setAssigning(true);
    const profile = selectedService === 'hotspot' ? 'billing-saas-captive' : 'default';
    try {
      let data;
      try {
        ({ data } = await api.post('/router/ports', {
          interfaces: selectedPorts,
          service_type: selectedService,
          profile,
        }));
      } catch (error) {
        data = error.response?.data;
        if (!data?.results) throw error;
      }
      const failedPorts = (data.results || [])
        .filter((item) => !item.success)
        .map((item) => item.interface);
      const assignedCount = selectedPorts.length - failedPorts.length;
      setSelectedPorts(failedPorts);
      if (assignedCount > 0) {
        toast.success(`${assignedCount} port${assignedCount === 1 ? '' : 's'} assigned to ${serviceLabel(selectedService)}`);
        await pullRouterStatus({ silent: true });
      }
      if (failedPorts.length > 0) {
        toast.error(`Could not assign ${failedPorts.map(portLabel).join(', ')}. They remain selected so you can retry.`);
      }
    } catch (error) {
      toast.error(error.response?.data?.message || 'Could not assign the selected ports');
    } finally {
      setAssigning(false);
    }
  };

  if (loading) return <p className="text-sm font-medium text-slate-600">Loading MikroTik configuration...</p>;

  return (
    <div className="space-y-3 text-[13px] font-normal tracking-[0.005em]">
      {migrationSummary && Object.keys(migrationSummary).length > 0 && (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-950">
          <p className="font-semibold">{migrationSummary.error ? 'Router migration import failed' : 'Router migration imported into Customers'}</p>
          <p className="mt-1 text-xs">
            {migrationSummary.error
              ? migrationSummary.error
              : (migrationSummary.created || 0) + ' new, ' + (migrationSummary.updated || 0) + ' updated'
                + (migrationSummary.skipped ? ', ' + migrationSummary.skipped + ' skipped because a readable username/password was unavailable' : '')
                + (migrationSummary.conflicts ? ', ' + migrationSummary.conflicts + ' username conflicts to review' : '') + '.'}
          </p>
        </div>
      )}
      {showProvisioning && (
        <section id="link-mikrotik" className={`surface-card p-3 sm:p-4 ${activeStep === 'link' ? '' : 'hidden'}`}>
          <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h1 className="page-title">{isAddingRouter ? 'Add another MikroTik device' : 'Link MikroTik Device'}</h1>
            </div>
          </div>
          <div className="flex justify-end">
            <button type="button" className="btn-secondary" onClick={loadProvisionCommand}>
              <RefreshCw size={16} />
              New Command
            </button>
          </div>
          <div className="mt-3 grid gap-2 rounded-lg border border-[var(--app-border)] bg-[var(--app-panel-muted)] p-3">
            <label className="block">
              <span className="form-label">MikroTik name</span>
              <input
                className="form-input theme-input"
                value={routerName}
                onChange={(event) => setRouterName(event.target.value)}
                placeholder="Main office router"
              />
            </label>
          </div>
          <label className="mt-3 flex cursor-pointer items-start gap-3 rounded-lg border border-[var(--app-border)] bg-[var(--app-panel-muted)] p-3">
            <input
              type="checkbox"
              className="mt-1 h-4 w-4 rounded border-slate-300 text-[var(--app-accent)] focus:ring-[var(--app-accent)]"
              checked={migrationMode}
              onChange={(event) => setMigrationMode(event.target.checked)}
            />
            <span>
              <span className="block text-sm font-normal text-[var(--app-text)]">Migrate existing router data</span>
              <span className="mt-0.5 block text-xs text-[var(--app-muted)]">Capture PPPoE and Hotspot accounts, profiles, simple queue limits, and active sessions before provisioning.</span>
            </span>
          </label>
          <div className="mt-3 overflow-hidden rounded-lg border border-[var(--app-border)] bg-[var(--app-panel)] text-[var(--app-text)]">
            <div className="grid gap-2 px-3 pt-3 sm:grid-cols-[1fr_auto] sm:items-center">
              <span className="text-xs font-medium uppercase tracking-wide text-[var(--app-muted)]">{provision?.mode === 'migration' ? 'Migration export command' : 'Router terminal'}</span>
              <button type="button" className="btn-secondary justify-center sm:w-auto" onClick={() => copy(provision?.command, 'Command')} disabled={!provision?.command}>
                <Clipboard size={15} />
                Copy
              </button>
            </div>
            <textarea
              className="theme-input mx-3 mb-3 mt-2 block h-28 w-[calc(100%-1.5rem)] resize-none rounded-md border border-[var(--app-border)] p-3 font-mono text-xs leading-5 outline-none"
              readOnly
              spellCheck="false"
              value={provision?.command || 'Generating command...'}
              onFocus={(event) => event.target.select()}
            />
            {provision?.mode === 'migration' && (
              <p className="px-3 pb-3 text-xs font-normal text-[var(--app-muted)]">The router sends its existing accounts to Expressnet. Credentials with readable passwords are added to Customers; turn this off to provision the router.</p>
            )}
            <div className="grid gap-2 border-t border-[var(--app-border)] bg-[var(--app-panel-muted)] px-3 py-2 sm:grid-cols-[1fr_auto] sm:items-center">
              <div className="min-w-0">
                <p className="text-xs font-normal leading-5 text-[var(--app-text)]">If needed, switch the device to advanced mode:</p>
                <pre className="theme-input mt-2 overflow-auto whitespace-pre-wrap break-all rounded-md border border-[var(--app-border)] px-3 py-2 font-mono text-xs leading-5">/system/device-mode/update mode=advanced</pre>
              </div>
              <button type="button" className="btn-secondary justify-center sm:w-auto" onClick={() => copy('/system/device-mode/update mode=advanced', 'Advanced mode command')}>
                <Clipboard size={15} />
                Copy
              </button>
            </div>
          </div>
          <div className="mt-3 flex justify-end">
            <button type="button" className="btn-primary" onClick={goToConfiguration} disabled={pullingStatus}>
              {pullingStatus ? 'Pulling live config...' : 'Next'}
              <ArrowRight size={16} />
            </button>
          </div>
        </section>
      )}

      {(!showProvisioning || activeStep === 'configure') && (
      <section className="rounded-[10px] border-1 border-slate-300 bg-white p-4 sm:p-8">
        <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-base font-bold text-slate-950">Router configurations</h2>
            <p className="mt-1 text-sm text-slate-600">Select any number of customer ports, choose a service, then assign them together. PPPoE + Hotspot applies both services to each selected port.</p>
          </div>
        </div>

        {routerStatus ? (
          <div className="space-y-5">
            {(routerStatus.source === 'provisioning_snapshot' || routerStatus.source === 'provisioning_seen') && (
              <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
                {routerStatus.message || 'Showing the last config pushed by the router during provisioning.'}
              </div>
            )}

            <div className="rounded-[10px] border border-slate-300 shadow-2xs bodder-white bg-white p-4 sm:p-6">
              <div className="grid gap-4 sm:grid-cols-2">
                {[
                  ['pppoe', PlugZap, 'PPPoE'],
                  ['hotspot', Wifi, 'Hotspot'],
                ].map(([key, Icon, label]) => {
                  const active = selectedServices.includes(key);
                  return (
                    <label
                      key={key}
                      className="flex h-12 cursor-pointer items-center rounded-full border border-slate-400 bg-white px-4 text-sm font-semibold text-slate-700 transition hover:border-[var(--app-accent)]"
                      style={active ? { borderColor: 'var(--app-accent)', background: 'var(--app-accent-muted)', color: 'var(--app-text)' } : undefined}
                    >
                      <input
                        className="sr-only"
                        type="checkbox"
                        checked={active}
                        onChange={() => toggleService(key)}
                      />
                      <span
                        className="mr-4 flex h-7 w-7 items-center justify-center rounded-full border-2"
                        style={active ? { borderColor: 'var(--app-accent)', background: 'var(--app-accent)', color: 'var(--app-accent-contrast)' } : { borderColor: 'var(--app-accent)', background: 'var(--app-panel)', color: 'var(--app-accent)' }}
                      >
                        <Icon size={15} />
                      </span>
                      <span className="flex-1 text-center">{label}</span>
                    </label>
                  );
                })}
              </div>

              <div className="mt-6 flex items-center justify-between gap-3">
                <p className="text-sm font-semibold text-slate-700">Select customer ports{selectedPorts.length ? ` (${selectedPorts.length} selected)` : ''}</p>
                <button type="button" className="btn-secondary" onClick={toggleAllPorts} disabled={selectablePorts.length === 0}>
                  {allSelectablePortsSelected ? 'Clear selection' : 'Select all'}
                </button>
              </div>
              <div className="mt-3 grid gap-4 sm:grid-cols-2">
                {(routerStatus.interfaces || []).map((item) => {
                  const selected = selectedPorts.includes(item.name);
                  const assigned = routerStatus.assignments?.[item.name];
                  const blocked = item.customer_assignable === false;
                  return (
                    <button
                      key={item.id || item.name}
                      type="button"
                      className={`min-h-16 rounded-[20px] border border-slate-400 bg-white px-4 py-3 text-sm font-semibold text-slate-700 transition hover:border-[var(--app-accent)] disabled:cursor-not-allowed disabled:opacity-50 ${assigned ? 'ring-2 ring-[var(--app-focus-ring)]' : ''}`}
                      style={selected ? { borderColor: 'var(--app-accent)', background: 'var(--app-accent)', color: 'var(--app-accent-contrast)' } : assigned ? { borderColor: 'var(--app-accent)', background: 'var(--app-accent-muted)' } : undefined}
                      onClick={() => togglePort(item.name)}
                      disabled={blocked}
                      title={blocked ? `${portLabel(item.name)} is ${item.assignment_warning || 'not assignable'}` : assigned ? `${portLabel(item.name)} assigned to ${serviceLabel(assigned.service_type)}` : portLabel(item.name)}
                      aria-pressed={selected}
                    >
                      <span className="flex items-center justify-center gap-2">
                        <EthernetPort size={18} />
                        {portLabel(item.name)}{blocked ? ' - WAN' : ''}
                      </span>
                      {selected && (
                        <span className="mt-1 block text-[11px] font-bold uppercase">
                          Selected
                        </span>
                      )}
                      {assigned && (
                        <span className="mt-1 block text-[11px] font-bold uppercase text-[var(--app-accent)]">
                          {serviceLabel(assigned.service_type)} assigned
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>

              {(routerStatus.interfaces || []).length === 0 && (
                <div className="mt-6 rounded-2xl border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500">
                  No assignable physical ports have been reported yet.
                </div>
              )}

              <div className="mt-6 flex justify-end">
                <button type="button" className="h-11 min-w-56 rounded-full border border-slate-400 bg-white px-6 text-sm font-semibold text-slate-800 transition hover:border-[var(--app-accent)] hover:text-[var(--app-accent)] disabled:cursor-not-allowed disabled:opacity-50" onClick={assignPorts} disabled={assigning || selectedPorts.length === 0}>
                  {assigning ? 'Assigning...' : `Assign ${serviceLabel(selectedService)} to selected ports`}
                </button>
              </div>
            </div>
          </div>
        ) : (
          <div className="rounded-3xl border border-slate-400 bg-white p-8 text-center">
            <p className="text-sm font-semibold text-slate-700">Live router configuration was not available yet. Go back and click Next after the router has reported in.</p>
          </div>
        )}
      </section>
      )}
    </div>
  );
}
