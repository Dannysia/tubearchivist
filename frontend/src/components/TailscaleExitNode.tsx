import { useEffect, useMemo, useState } from 'react';
import loadTailscaleState, {
  TailscaleNodeType,
  TailscaleStateType,
} from '../api/loader/loadTailscaleState';
import loadTailscaleEgress, { TailscaleEgressType } from '../api/loader/loadTailscaleEgress';
import updateTailscaleExitNode, {
  ExitNodeActionType,
} from '../api/actions/updateTailscaleExitNode';
import { ApiError } from '../functions/APIClient';
import { useUserConfigStore } from '../stores/UserConfigStore';
import Button from './Button';

const describeNode = (node: TailscaleNodeType) => {
  const where = [node.city, node.country].filter(Boolean).join(', ');

  return where ? `${node.hostname} — ${where}` : node.hostname;
};

const describeEgress = (egress: TailscaleEgressType) => {
  const where = [egress.city, egress.country].filter(Boolean).join(', ');

  if (egress.is_mullvad && egress.exit_hostname) {
    return `${where}, via ${egress.exit_hostname}`;
  }

  if (egress.is_mullvad === false) {
    const org = egress.organization ? ` (${egress.organization})` : '';
    return `${where}${org} — not going through an exit node`;
  }

  // the mullvad check was unreachable, so only the address itself is known
  return 'exit node could not be confirmed';
};

const errorMessage = (err: unknown, fallback: string) => (err as ApiError)?.message || fallback;

const TailscaleExitNode = () => {
  const { userConfig } = useUserConfigStore();
  const [state, setState] = useState<TailscaleStateType>();
  const [country, setCountry] = useState('');
  const [nodeId, setNodeId] = useState('');
  const [egress, setEgress] = useState<TailscaleEgressType>();
  const [checking, setChecking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [loadError, setLoadError] = useState('');
  // distinguishes the first read not having landed yet from it having
  // landed and found nothing, which render very differently
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const response = await loadTailscaleState();
        if (response.data) {
          setState(response.data);
          setCountry(response.data.current?.country ?? '');
          setNodeId(response.data.current?.node_id ?? '');
        } else {
          // a socket that is there but will not answer, which is the
          // most worth saying out loud of all the failures here
          setLoadError(response.error?.error ?? 'could not read tailscale state');
        }
      } catch (err) {
        setLoadError(errorMessage(err, 'could not read tailscale state'));
      }
      setLoaded(true);
    })();
  }, []);

  const countries = useMemo(() => {
    const named = (state?.nodes ?? []).map(node => node.country).filter(Boolean);

    return [...new Set(named as string[])].sort();
  }, [state]);

  // a node with no country is one of the user's own machines, which is
  // what the empty country groups together
  const selectable = useMemo(
    () => (state?.nodes ?? []).filter(node => (node.country ?? '') === country),
    [state, country],
  );

  const hasOwnNodes = useMemo(() => (state?.nodes ?? []).some(node => !node.is_mullvad), [state]);

  const checkEgress = async () => {
    setChecking(true);
    setEgress(undefined);
    try {
      const response = await loadTailscaleEgress();
      if (response.data) {
        setEgress(response.data);
      } else {
        setError(response.error?.error ?? 'could not read the egress address');
      }
    } catch (err) {
      setError(errorMessage(err, 'could not read the egress address'));
    }
    setChecking(false);
  };

  const runAction = async (action: ExitNodeActionType, pickedId?: string) => {
    setBusy(true);
    setError('');
    try {
      const response = await updateTailscaleExitNode(action, pickedId);
      if (response.data) {
        setState(response.data);
        setCountry(response.data.current?.country ?? '');
        setNodeId(response.data.current?.node_id ?? '');
        // the address only moves once tailscaled has re-routed, so the
        // readout is worth nothing until after the change landed
        await checkEgress();
      } else {
        setError(response.error?.error ?? 'exit node change failed');
      }
    } catch (err) {
      setError(errorMessage(err, 'exit node change failed'));
    }
    setBusy(false);
  };

  // nothing at all until the first read lands, so the panel does not
  // flash an absence it is about to contradict
  if (!loaded) {
    return null;
  }

  // there is nothing to steer, but say so rather than vanishing: a panel
  // that silently disappears is indistinguishable from one that was
  // never built, and hides the case where tailscale is meant to be here
  if (loadError || !state?.available) {
    return (
      <div className="info-box-item">
        <h2 id="exit-node">Tailscale exit node</h2>
        {userConfig.show_help_text && (
          <div className="help-text">
            <ul>
              <li>
                Switches the address this container&apos;s traffic leaves through, for when YouTube
                refuses the current one.
              </li>
              <li>
                It needs a tailscaled running inside this container, as Unraid&apos;s tailscale
                integration provides. Nothing on this page can turn that on.
              </li>
            </ul>
          </div>
        )}
        {loadError ? (
          <p>
            <span className="danger-zone">Tailscale present but not answering</span>: {loadError}
          </p>
        ) : (
          <p>
            <span className="settings-current">Tailscale not detected</span> — no tailscaled socket
            in this container, so there is no exit node to switch.
          </p>
        )}
      </div>
    );
  }

  return (
    <div className="info-box-item">
      <h2 id="exit-node">Tailscale exit node</h2>
      {userConfig.show_help_text && (
        <div className="help-text">
          <ul>
            <li>
              Sends this container&apos;s traffic out through a different address, for when YouTube
              refuses the current one. The same problem the rate limits and sleep interval above
              address, approached from the other end.
            </li>
            <li>
              Rotate picks a random Mullvad node anywhere in the world.
              <ul>
                <li>
                  Your own tailnet exit nodes are never picked. They sit on the connection being
                  rotated away from, so they would not change the address at all.
                </li>
                <li>Pick from the lists instead to choose a country deliberately.</li>
              </ul>
            </li>
            <li>Changes apply immediately, with no restart.</li>
            <li>
              Unraid re-applies its own exit node setting when the container starts, so a change
              made here holds only until the next restart.
            </li>
            <li>
              Check address asks Mullvad which node the traffic actually came out of, the only way
              to confirm a switch did anything.
            </li>
          </ul>
        </div>
      )}
      {!state.routes_all_traffic && (
        <p>
          <span className="danger-zone">Userspace networking</span>: tailscaled here is not routing
          all traffic, so changing the exit node will not move downloads.
        </p>
      )}
      <div id="tailscale-exit-node">
        <div className="settings-box-wrapper">
          <div>
            <p>Current exit node</p>
          </div>
          <p>
            <span className="settings-current">
              {state.current ? describeNode(state.current) : 'direct, no exit node'}
            </span>
          </p>
        </div>
        <div className="settings-box-wrapper">
          <div>
            <p>Address seen by YouTube</p>
          </div>
          <div>
            {egress && (
              <p>
                <span className="settings-current">{egress.ip}</span> {describeEgress(egress)}
              </p>
            )}
            <Button
              label={checking ? 'Checking' : 'Check address'}
              disabled={checking || busy}
              onClick={checkEgress}
            />
          </div>
        </div>
        <div className="settings-box-wrapper">
          <div>
            <p>Pick a node</p>
          </div>
          <div>
            <select
              value={country}
              onChange={event => {
                setCountry(event.target.value);
                setNodeId('');
              }}
            >
              <option value="">{hasOwnNodes ? 'Own tailnet machines' : 'Select a country'}</option>
              {countries.map(name => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>{' '}
            <select value={nodeId} onChange={event => setNodeId(event.target.value)}>
              <option value="">Select a node</option>
              {selectable.map(node => (
                <option key={node.node_id} value={node.node_id} disabled={!node.online}>
                  {node.city ? `${node.city} — ` : ''}
                  {node.hostname}
                  {node.online ? '' : ' (offline)'}
                </option>
              ))}
            </select>
          </div>
        </div>
        <Button
          label="Apply"
          disabled={busy || !nodeId || nodeId === state.current?.node_id}
          onClick={() => runAction('set', nodeId)}
        />{' '}
        <Button
          label="Rotate"
          title="switch to a random Mullvad node anywhere, never one of your own machines"
          disabled={busy}
          onClick={() => runAction('rotate')}
        />{' '}
        <Button
          label="Go direct"
          title="stop using an exit node"
          disabled={busy || !state.current}
          onClick={() => runAction('clear')}
        />
        {error && (
          <p>
            <span className="danger-zone">{error}</span>
          </p>
        )}
      </div>
    </div>
  );
};

export default TailscaleExitNode;
