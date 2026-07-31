import { useEffect, useState } from 'react';
import { useOutletContext, useSearchParams } from 'react-router-dom';
import { Fragment } from 'react/jsx-runtime';
import { OutletContextType } from './Base';
import { ConfigType } from './Home';
import Pagination, { PaginationType } from '../components/Pagination';
import Button from '../components/Button';
import DownscaleListItem from '../components/DownscaleListItem';
import loadDownscaleQueue, {
  DownscaleSizeChange,
  DownscaleStatus,
} from '../api/loader/loadDownscaleQueue';
import loadDownscaleAggs, { DownscaleAggsType } from '../api/loader/loadDownscaleAggs';
import updateDownscaleQueueByIds, {
  DownscaleBulkAction,
} from '../api/actions/updateDownscaleQueueByIds';
import updateDownscaleQueueByFilter from '../api/actions/updateDownscaleQueueByFilter';
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
  const sizeChangeFilterFromUrl = searchParams.get('size_change') as DownscaleSizeChange | null;

  const [refreshNonce, setRefreshNonce] = useState(0);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [searchInput, setSearchInput] = useState('');
  const [showBulkRejectConfirm, setShowBulkRejectConfirm] = useState(false);
  const [filterActionPending, setFilterActionPending] = useState<DownscaleBulkAction | null>(null);
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

  const selectableIds = jobList?.map(job => job.id);
  const allSelected = !!selectableIds?.length && selectableIds.every(id => selectedIds.has(id));

  // queued/running jobs need the 'cancel' action to actually stop the
  // encode - accept/reject/retry only ever touch the queue doc, so
  // running one of those on a still-encoding job would just orphan it,
  // not cancel it
  const cancelableSelectedJobs =
    jobList?.filter(
      job => selectedIds.has(job.id) && (job.status === 'queued' || job.status === 'running'),
    ) ?? [];
  const reviewableSelectedIds = [...selectedIds].filter(
    id => !cancelableSelectedJobs.some(job => job.id === id),
  );

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
        sizeChangeFilterFromUrl,
      );
      setDownscaleResponse(response);
    })();
  }, [
    currentPage,
    statusFilterFromUrl,
    channelFilterFromUrl,
    searchInput,
    sizeChangeFilterFromUrl,
    refreshNonce,
  ]);

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
    await updateDownscaleQueueByIds(reviewableSelectedIds, action);
    setSelectedIds(new Set());
    setShowBulkRejectConfirm(false);
    refreshQueue();
  };

  const handleBulkCancel = async () => {
    await updateDownscaleQueueByIds(
      cancelableSelectedJobs.map(job => job.id),
      'cancel',
    );
    setSelectedIds(new Set());
    setShowBulkRejectConfirm(false);
    refreshQueue();
  };

  const handleFilterAction = async (action: DownscaleBulkAction) => {
    await updateDownscaleQueueByFilter(
      action,
      statusFilterFromUrl,
      channelFilterFromUrl,
      searchInput,
      sizeChangeFilterFromUrl,
    );
    setFilterActionPending(null);
    setSelectedIds(new Set());
    setShowBulkRejectConfirm(false);
    refreshQueue();
  };

  const renderFilterActionButton = (action: DownscaleBulkAction, label: string) => {
    if (filterActionPending === action) {
      return (
        <span key={action} className="delete-confirm">
          <span>Are you sure? </span>
          <Button
            label="Confirm"
            className="danger-button"
            onClick={() => handleFilterAction(action)}
          />
          <Button label="Cancel" onClick={() => setFilterActionPending(null)} />
        </span>
      );
    }

    return (
      <Button
        key={action}
        label={label}
        className={action === 'reject' || action === 'cancel' ? 'danger-button' : ''}
        onClick={() => setFilterActionPending(action)}
      />
    );
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
          <select
            name="size_change_filter"
            id="size_change_filter"
            value={sizeChangeFilterFromUrl || 'all'}
            onChange={event => {
              const value = event.currentTarget.value;
              const params = searchParams;
              if (value !== 'all') {
                params.set('size_change', value);
              } else {
                params.delete('size_change');
              }
              setSearchParams(params);
              setSelectedIds(new Set());
              setShowBulkRejectConfirm(false);
            }}
          >
            <option value="all">any size change</option>
            <option value="smaller">got smaller</option>
            <option value="larger">got larger</option>
          </select>
        </div>

        <h3>
          {channelFilterFromUrl && (
            <>
              Filtered by channel: <i>{channel_filter_name}</i>
            </>
          )}
          {sizeChangeFilterFromUrl && (
            <>
              {channelFilterFromUrl && ' - '}
              Filtered by size change: <i>{sizeChangeFilterFromUrl}</i>
            </>
          )}
        </h3>

        {!!pagination?.total_hits &&
          (statusFilterFromUrl === 'pending_review' ||
          statusFilterFromUrl === 'failed' ||
          statusFilterFromUrl === 'queued' ||
          statusFilterFromUrl === 'running' ? (
            <div className="button-box">
              {statusFilterFromUrl === 'pending_review' && (
                <>
                  {renderFilterActionButton(
                    'accept',
                    `Accept All Matching Filter (${pagination.total_hits})`,
                  )}
                  {renderFilterActionButton(
                    'reject',
                    `Reject All Matching Filter (${pagination.total_hits})`,
                  )}
                </>
              )}
              {statusFilterFromUrl === 'failed' &&
                renderFilterActionButton(
                  'retry',
                  `Retry All Matching Filter (${pagination.total_hits})`,
                )}
              {(statusFilterFromUrl === 'queued' || statusFilterFromUrl === 'running') &&
                renderFilterActionButton(
                  'cancel',
                  `Cancel All Matching Filter (${pagination.total_hits})`,
                )}
            </div>
          ) : (
            <p className="settings-current">
              Pick a status filter above (pending review, failed, queued, or running) to enable a
              bulk action on everything matching it.
            </p>
          ))}

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
            {reviewableSelectedIds.length > 0 && (
              <>
                <Button
                  label={`Accept Selected (${reviewableSelectedIds.length})`}
                  onClick={() => handleBulkAction('accept')}
                />
                <Button
                  label={`Retry Selected (${reviewableSelectedIds.length})`}
                  onClick={() => handleBulkAction('retry')}
                />
                {showBulkRejectConfirm ? (
                  <>
                    <Button
                      label={`Confirm Reject (${reviewableSelectedIds.length})`}
                      className="danger-button"
                      onClick={() => handleBulkAction('reject')}
                    />
                    <Button onClick={() => setShowBulkRejectConfirm(false)}>Cancel</Button>
                  </>
                ) : (
                  <Button
                    label={`Reject Selected (${reviewableSelectedIds.length})`}
                    className="danger-button"
                    onClick={() => setShowBulkRejectConfirm(true)}
                  />
                )}
              </>
            )}
            {cancelableSelectedJobs.length > 0 && (
              <Button
                label={`Cancel Selected (${cancelableSelectedJobs.length})`}
                className="danger-button"
                onClick={handleBulkCancel}
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
