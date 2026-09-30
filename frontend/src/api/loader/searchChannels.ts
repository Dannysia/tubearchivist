import APIClient from '../../functions/APIClient';
import { ChannelType } from '../../pages/Channels';

type ChannelSearchResponse = {
  results: {
    channel_results: ChannelType[];
  };
};

const searchChannels = async (term: string) => {
  const query = encodeURIComponent(`channel:${term}`);

  return APIClient<ChannelSearchResponse>(`/api/search/?query=${query}`);
};

export default searchChannels;
