import { useEffect, useState } from 'react';
import { useOutletContext, useSearchParams } from 'react-router-dom';
import { Fragment } from 'react/jsx-runtime';
import { OutletContextType } from './Base';
import { ConfigType } from './Home';
import Pagination, { PaginationType } from '../components/Pagination';
import Button from '../components/Button';
import DownscaleListItem from '../components/DownscaleListItem';
import loadDownscaleQueue, { DownscaleStatus } from '../api/loader/loadDownscaleQueue';
import loadDownscaleAggs, { DownscaleAggsType } from '../api/loader/loadDownscaleAggs';
import updateDownscaleQueueByIds, {
  DownscaleBulkAction,
} from '../api/actions/updateDownscaleQueueByIds';
import loadNotifications from '../api/loader/loadNotifications';
import { ApiResponseType } from '../functions/APIClient';

export type DownscaleJob = {
  id: string;
  youtube_id: string;
  channel_id: string;
  channel_name: string;
  title: string;
  vid_thumb_url?: string;
  media_url: string;
  status: DownscaleStatus;
  current_height: number;
  target_height: number;
  original_size: number;
  new_size: number;
  tmp_file_path: string;
  task_id: string;
  timestamp: number;
  updated: number;
  message?: string;
};

export type DownscaleResponseType = {
  data?: DownscaleJob[];
  config?: ConfigType;
  paginate?: PaginationType;
};

const Downscale = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const { currentPage, setCurrentPage } = useOutletContext() as OutletContextType;

  const statusFilterFromUrl = searchParams.get('status') as DownscaleStatus | null;
  const channelFilterFromUrl = searchParams.get('channel');

  const [refreshNonce, setRefreshNonce] = useState(0);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [searchInput, setSearchInput] = useState('');
  const [showBulkRejectConfirm, setShowBulkRejectConfirm] = useState(false);
  const [downscaleResponse, setDownscaleResponse] =
    useState<ApiResponseType<DownscaleResponseType>>();
  const [downscaleAggsResponse, setDownscaleAggsResponse] =
    useState<ApiResponseType<DownscaleAggsType>>();
  const [progressByTaskId, setProgressByTaskId] = useState<Record<string, number>>({});

  const { data: downscaleResponseData } = downscaleResponse ?? {};
  const { data: downscaleAggsResponseData } = downscaleAggsResponse ?? {};
  const jobList = downscaleResponseData?.data;
  const pagination = downscaleResponseData?.paginate;
  const channelAggsList = downscaleAggsResponseData?.buckets;

  const channel_filter_name = jobList?.length ? jobList[0].channel_name : '';

  const hasActiveJob =
    jobList?.some(job => job.status === 'running' || job.status === 'queued') ?? false;

  const selectableIds = jobList
    ?.filter(job => job.status !== 'running' && job.status !== 'queued')
    .map(job => job.id);
  const allSelected =
    !!selectableIds?.length && selectableIds.every(id => selectedIds.has(id));

  const refreshQueue = () => {
    setRefreshNonce(current => current + 1);
  };

  useEffect(() => {
    (async () => {
      const response = await loadDownscaleQueue(
        currentPage,
        statusFilterFromUrl,
        channelFilterFromUrl,
        searchInput,
      );
      setDownscaleResponse(response);
    })();
  }, [currentPage, statusFilterFromUrl, channelFilterFromUrl, searchInput, refreshNonce]);

  useEffect(() => {
    (async () => {
      const response = await loadDownscaleAggs(statusFilterFromUrl);
      setDownscaleAggsResponse(response);
    })();
  }, [statusFilterFromUrl, refreshNonce]);

  useEffect(() => {
    if (!hasActiveJob) {
      return;
    }

    const intervalId = setInterval(async () => {
      const response = await loadNotifications('downscale');
      const { data } = response ?? {};

      if (!data || data.length === 0) {
        clearInterval(intervalId);
        refreshQueue();
        return;
      }

      const nextProgress: Record<string, number> = {};
      data.forEach(notification => {
        nextProgress[notification.id] = notification.progress || 0;
      });
      setProgressByTaskId(nextProgress);
    }, 1000);

    return () => clearInterval(intervalId);
  }, [hasActiveJob]);

  const handleSetPage = (page: number) => {
    setSelectedIds(new Set());
    setShowBulkRejectConfirm(false);
    setCurrentPage(page);
  };

  const toggleSelected = (id: string) => {
    setSelectedIds(current => {
      const updated = new Set(current);
      if (updated.has(id)) {
        updated.delete(id);
      } else {
        updated.add(id);
      }
      return updated;
    });
  };

  const toggleSelectAll = () => {
    if (allSelected) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(selectableIds));
    }
  };

  const handleBulkAction = async (action: DownscaleBulkAction) => {
    await updateDownscaleQueueByIds([...selectedIds], action);
    setSelectedIds(new Set());
    setShowBulkRejectConfirm(false);
    refreshQueue();
  };

  return (
    <>
      <title>TA | Downscale Queue</title>
      <div className="boxed-content">
        <div className="title-bar">
          <h1>Downscale Queue</h1>
        </div>

        <div className="view-controls three">
          <select
            name="status_filter"
            id="status_filter"
            value={statusFilterFromUrl || 'all'}
            onChange={event => {
              const value = event.currentTarget.value;
              const params = searchParams;
              if (value !== 'all') {
                params.set('status', value);
              } else {
                params.delete('status');
              }
              setSearchParams(params);
              setSelectedIds(new Set());
              setShowBulkRejectConfirm(false);
            }}
          >
            <option value="all">all statuses</option>
            <option value="queued">queued</option>
            <option value="running">running</option>
            <option value="pending_review">pending review</option>
            <option value="failed">failed</option>
            <option value="cancelled">cancelled</option>
          </select>
          {channelAggsList && channelAggsList.length > 0 && (
            <select
              name="channel_filter"
              id="channel_filter"
              value={channelFilterFromUrl || 'all'}
              onChange={event => {
                const value = event.currentTarget.value;
                const params = searchParams;
                if (value !== 'all') {
                  params.set('channel', value);
                } else {
                  params.delete('channel');
                }
                setSearchParams(params);
                setSelectedIds(new Set());
                setShowBulkRejectConfirm(false);
              }}
            >
              <option value="all">all channels</option>
              {channelAggsList.map(channel => {
                const [name, id] = channel.key;
                const count = channel.doc_count;

                return (
                  <option key={id} value={id}>
                    {name} ({count})
                  </option>
                );
              })}
            </select>
          )}
          <input
            type="text"
            placeholder="Search..."
            value={searchInput}
            onChange={event => {
              setSearchInput(event.target.value);
              setSelectedIds(new Set());
              setShowBulkRejectConfirm(false);
            }}
          />
          {searchInput && <Button onClick={() => setSearchInput('')}>Clear</Button>}
        </div>

        <h3>
          {channelFilterFromUrl && (
            <>
              Filtered by channel: <i>{channel_filter_name}</i>
            </>
          )}
        </h3>

        <div className="button-box">
          {!!selectableIds?.length && (
            <span className="toggle">
              <input
                id="select_all_downscale"
                type="checkbox"
                checked={allSelected}
                onChange={toggleSelectAll}
              />
              <label htmlFor="select_all_downscale">
                {allSelected ? 'Deselect all' : 'Select all'}
              </label>
            </span>
          )}
        </div>

        {selectedIds.size > 0 && (
          <div className="button-box">
            <Button
              label={`Accept Selected (${selectedIds.size})`}
              onClick={() => handleBulkAction('accept')}
            />
            <Button
              label={`Retry Selected (${selectedIds.size})`}
              onClick={() => handleBulkAction('retry')}
            />
            {showBulkRejectConfirm ? (
              <>
                <Button
                  label={`Confirm Reject (${selectedIds.size})`}
                  className="danger-button"
                  onClick={() => handleBulkAction('reject')}
                />
                <Button onClick={() => setShowBulkRejectConfirm(false)}>Cancel</Button>
              </>
            ) : (
              <Button
                label={`Reject Selected (${selectedIds.size})`}
                className="danger-button"
                onClick={() => setShowBulkRejectConfirm(true)}
              />
            )}
          </div>
        )}

        {jobList?.length === 0 && <p>No downscale jobs.</p>}
      </div>

      <div className="boxed-content">
        <div className="video-list list">
          {jobList?.map(job => {
            return (
              <Fragment key={job.id}>
                <DownscaleListItem
                  job={job}
                  isSelected={selectedIds.has(job.id)}
                  onToggle={toggleSelected}
                  setRefresh={refreshQueue}
                  progress={progressByTaskId[job.task_id]}
                />
              </Fragment>
            );
          })}
        </div>
      </div>

      <div className="boxed-content">
        {pagination && <Pagination pagination={pagination} setPage={handleSetPage} />}
      </div>
    </>
  );
};

export default Downscale;
