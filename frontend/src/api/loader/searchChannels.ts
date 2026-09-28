import APIClient from '../../functions/APIClient';
import { ChannelType } from '../../pages/Channels';

type ChannelSearchResponse = {
  results: {
    channel_results: ChannelType[];
  };
};

/** channel: scopes the search to ta_channel's channel_name.search_as_you_type */
const searchChannels = async (term: string) => {
  const query = encodeURIComponent(`channel:${term}`);

  return APIClient<ChannelSearchResponse>(`/api/search/?query=${query}`);
};

export default searchChannels;
