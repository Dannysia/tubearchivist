import APIClient from '../../functions/APIClient';

export type TailscaleEgressType = {
  ip: string | null;
  country: string | null;
  city: string | null;
  organization: string | null;
  // null when the check fell back to a plain ip echo, which cannot tell
  // whether the traffic left through an exit node
  is_mullvad: boolean | null;
  exit_hostname: string | null;
};

const loadTailscaleEgress = async () => {
  return APIClient<TailscaleEgressType>('/api/appsettings/tailscale/egress/');
};

export default loadTailscaleEgress;
