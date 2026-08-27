import APIClient from '../../functions/APIClient';
import { TailscaleStateType } from '../loader/loadTailscaleState';

export type ExitNodeActionType = 'set' | 'rotate' | 'clear';

const updateTailscaleExitNode = async (action: ExitNodeActionType, nodeId?: string) => {
  const body: Record<string, unknown> = { action };
  if (nodeId) {
    body.node_id = nodeId;
  }

  return APIClient<TailscaleStateType>('/api/appsettings/tailscale/', {
    method: 'POST',
    body,
  });
};

export default updateTailscaleExitNode;
