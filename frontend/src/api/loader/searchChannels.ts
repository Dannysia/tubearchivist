import APIClient from '../../functions/APIClient';
import { ChannelType } from '../../pages/Channels';

type ChannelSearchResponse = {
  results: {
    channel_results: ChannelType[];
  };
};

/**
 * Typeahead over indexed channels.
 *
 * The channel: prefix scopes SearchParser to ta_channel, which matches
 * on channel_name.search_as_you_type - see QueryBuilder._build_channel.
 */
const searchChannels = async (term: string) => {
  const query = encodeURIComponent(`channel:${term}`);

  return APIClient<ChannelSearchResponse>(`/api/search/?query=${query}`);
};

export default searchChannels;
