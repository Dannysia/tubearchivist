import APIClient from '../../functions/APIClient';

export type TailscaleNodeType = {
  node_id: string;
  hostname: string;
  country: string | null;
  city: string | null;
  online: boolean;
  is_mullvad: boolean;
};

export type TailscaleStateType = {
  available: boolean;
  routes_all_traffic: boolean;
  current: TailscaleNodeType | null;
  nodes: TailscaleNodeType[];
};

const loadTailscaleState = async () => {
  return APIClient<TailscaleStateType>('/api/appsettings/tailscale/');
};

export default loadTailscaleState;
