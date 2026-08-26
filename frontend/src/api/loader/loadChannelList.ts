import { PaginationType } from '../../components/Pagination';
import APIClient from '../../functions/APIClient';
import { ChannelType } from '../../pages/Channels';
import { ConfigType } from '../../pages/Home';
import { SortOrderType } from './loadVideoListByPage';

export type ChannelsListResponse = {
  data: ChannelType[];
  paginate: PaginationType;
  config?: ConfigType;
};

export type ChannelSortByType =
  | 'name'
  | 'subscribers'
  | 'last_refresh'
  | 'videos'
  | 'media_size'
  | 'duration'
  | 'last_download'
  | 'last_published'
  | 'watch_progress';

export const ChannelSortByEnum = {
  Name: 'name',
  Subscribers: 'subscribers',
  'Last Refresh': 'last_refresh',
  Videos: 'videos',
  'Media Size': 'media_size',
  Duration: 'duration',
  'Last Download': 'last_download',
  'Last Published': 'last_published',
  'Watch Progress': 'watch_progress',
};

type ChannelListFilterType = {
  page: number;
  showSubscribed: boolean | null;
  sort?: ChannelSortByType;
  order?: SortOrderType;
};

const loadChannelList = async ({ page, showSubscribed, sort, order }: ChannelListFilterType) => {
  const searchParams = new URLSearchParams();

  if (page) searchParams.append('page', page.toString());
  if (showSubscribed !== null) {
    searchParams.append('filter', showSubscribed ? 'subscribed' : 'unsubscribed');
  }
  if (sort) searchParams.append('sort', sort);
  if (order) searchParams.append('order', order);

  const endpoint = `/api/channel/${searchParams.toString() ? `?${searchParams.toString()}` : ''}`;

  return APIClient<ChannelsListResponse>(endpoint);
};

export default loadChannelList;
