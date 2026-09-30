import { useEffect, useState } from 'react';
import { useOutletContext, useSearchParams } from 'react-router-dom';
import { Fragment } from 'react/jsx-runtime';
import { OutletContextType } from './Base';
import { ConfigType } from './Home';
import Pagination, { PaginationType } from '../components/Pagination';
import Button from '../components/Button';
import DownscaleListItem from '../components/DownscaleListItem';
import loadDownscaleQueue, { DownscaleStatus } from '../api/loader/loadDownscaleQueue';
import loadDownscaleAggs, {
  DownscaleAggsType,
  DownscaleEncoderAggsType,
  DownscaleSavedAggsType,
  loadDownscaleEncoderAggs,
  loadDownscaleSavedAggs,
} from '../api/loader/loadDownscaleAggs';
import { ALL_ENCODER_LABELS } from '../configuration/constants/DownscaleEncoders';
import {
  DOWNSCALE_SIZE_CHANGES,
  DownscaleSizeChange,
  countsBySizeChange,
  sizeChangeLabel,
} from '../configuration/constants/DownscaleSizeChange';
import updateDownscaleQueueByIds, {
  DownscaleBulkAction,
  DownscaleBulkResultType,
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
  progress?: number | null;
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
  const encoderFilterFromUrl = searchParams.get('encoder');

  const [refreshNonce, setRefreshNonce] = useState(0);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [searchInput, setSearchInput] = useState('');
  const [showBulkRejectConfirm, setShowBulkRejectConfirm] = useState(false);
  const [filterActionPending, setFilterActionPending] = useState<DownscaleBulkAction | null>(null);
  const [downscaleResponse, setDownscaleResponse] =
    useState<ApiResponseType<DownscaleResponseType>>();
  const [downscaleAggsResponse, setDownscaleAggsResponse] =
    useState<ApiResponseType<DownscaleAggsType>>();
  const [downscaleEncoderAggsResponse, setDownscaleEncoderAggsResponse] =
    useState<ApiResponseType<DownscaleEncoderAggsType>>();
  const [downscaleSavedAggsResponse, setDownscaleSavedAggsResponse] =
    useState<ApiResponseType<DownscaleSavedAggsType>>();
  const [progressByTaskId, setProgressByTaskId] = useState<Record<string, number>>({});
  const [actionFailures, setActionFailures] = useState<DownscaleBulkResultType['failed']>([]);

  const { data: downscaleResponseData } = downscaleResponse ?? {};
  const { data: downscaleAggsResponseData } = downscaleAggsResponse ?? {};
  const { data: downscaleEncoderAggsResponseData } = downscaleEncoderAggsResponse ?? {};
  const { data: downscaleSavedAggsResponseData } = downscaleSavedAggsResponse ?? {};
  const jobList = downscaleResponseData?.data;
  const pagination = downscaleResponseData?.paginate;
  const channelAggsList = downscaleAggsResponseData?.buckets;
  const encoderAggsList = downscaleEncoderAggsResponseData?.buckets;
  const sizeChangeCounts = countsBySizeChange(downscaleSavedAggsResponseData);

  const channel_filter_name = jobList?.length ? jobList[0].channel_name : '';

  const hasActiveJob =
    jobList?.some(job => job.status === 'running' || job.status === 'queued') ?? false;
  const hasRemoteRunningJob =
    jobList?.some(job => job.status === 'running' && !job.task_id) ?? false;

  const selectableIds = jobList?.map(job => job.id);
  const allSelected = !!selectableIds?.length && selectableIds.every(id => selectedIds.has(id));

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
        encoderFilterFromUrl,
      );
      setDownscaleResponse(response);
    })();
  }, [
    currentPage,
    statusFilterFromUrl,
    channelFilterFromUrl,
    searchInput,
    sizeChangeFilterFromUrl,
    encoderFilterFromUrl,
    refreshNonce,
  ]);

  useEffect(() => {
    (async () => {
      const response = await loadDownscaleAggs(statusFilterFromUrl);
      setDownscaleAggsResponse(response);
    })();
  }, [statusFilterFromUrl, refreshNonce]);

  useEffect(() => {
    (async () => {
      const response = await loadDownscaleEncoderAggs(statusFilterFromUrl);
      setDownscaleEncoderAggsResponse(response);
    })();
  }, [statusFilterFromUrl, refreshNonce]);

  useEffect(() => {
    (async () => {
      const response = await loadDownscaleSavedAggs(statusFilterFromUrl);
      setDownscaleSavedAggsResponse(response);
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

  useEffect(() => {
    if (!hasRemoteRunningJob) {
      return;
    }

    const intervalId = setInterval(refreshQueue, 5000);
    return () => clearInterval(intervalId);
  }, [hasRemoteRunningJob]);

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

  const clearSelection = () => {
    setSelectedIds(new Set());
    setShowBulkRejectConfirm(false);
  };

  const setFilterParam = (key: string, value: string) => {
    const params = searchParams;
    if (value !== 'all') {
      params.set(key, value);
    } else {
      params.delete(key);
    }
    params.delete('page');
    setSearchParams(params);
    clearSelection();
  };

  const setSearch = (value: string) => {
    setSearchInput(value);
    clearSelection();
    if (currentPage !== 0) {
      setCurrentPage(0);
    }
  };

  const recordResult = async (request: Promise<ApiResponseType<DownscaleBulkResultType>>) => {
    try {
      const response = await request;
      if (response.data) {
        setActionFailures(response.data.failed);
        return;
      }

      setActionFailures([{ id: '', error: `request failed with status ${response.status}` }]);
    } catch (error) {
      const message = (error as { message?: string })?.message ?? 'request failed';
      setActionFailures([{ id: '', error: message }]);
    }
  };

  const runAction = async (ids: string[], action: DownscaleBulkAction) => {
    await recordResult(updateDownscaleQueueByIds(ids, action));
    refreshQueue();
  };

  const handleBulkAction = async (action: DownscaleBulkAction) => {
    await runAction(reviewableSelectedIds, action);
    setSelectedIds(new Set());
    setShowBulkRejectConfirm(false);
  };

  const handleBulkCancel = async () => {
    await runAction(
      cancelableSelectedJobs.map(job => job.id),
      'cancel',
    );
    setSelectedIds(new Set());
    setShowBulkRejectConfirm(false);
  };

  const handleFilterAction = async (action: DownscaleBulkAction) => {
    await recordResult(
      updateDownscaleQueueByFilter(
        action,
        statusFilterFromUrl,
        channelFilterFromUrl,
        searchInput,
        sizeChangeFilterFromUrl,
        encoderFilterFromUrl,
      ),
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
            onChange={event => setFilterParam('status', event.currentTarget.value)}
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
              onChange={event => setFilterParam('channel', event.currentTarget.value)}
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
            onChange={event => setSearch(event.target.value)}
          />
          {searchInput && <Button onClick={() => setSearch('')}>Clear</Button>}
          <select
            name="size_change_filter"
            id="size_change_filter"
            value={sizeChangeFilterFromUrl || 'all'}
            onChange={event => setFilterParam('size_change', event.currentTarget.value)}
          >
            <option value="all">any size change</option>
            {DOWNSCALE_SIZE_CHANGES.map(({ value, label }) => {
              const count = sizeChangeCounts[value];

              return (
                <option key={value} value={value}>
                  {label}
                  {count === undefined ? '' : ` (${count})`}
                </option>
              );
            })}
          </select>
          {encoderAggsList && encoderAggsList.length > 0 && (
            <select
              name="encoder_filter"
              id="encoder_filter"
              value={encoderFilterFromUrl || 'all'}
              onChange={event => setFilterParam('encoder', event.currentTarget.value)}
            >
              <option value="all">all encoders</option>
              {encoderAggsList.map(encoderBucket => (
                <option key={encoderBucket.key} value={encoderBucket.key}>
                  {ALL_ENCODER_LABELS[encoderBucket.key] ?? encoderBucket.key} (
                  {encoderBucket.doc_count})
                </option>
              ))}
            </select>
          )}
        </div>

        <h3>
          {channelFilterFromUrl && (
            <>
              Filtered by channel: <i>{channel_filter_name}</i>
            </>
          )}
          {encoderFilterFromUrl && (
            <>
              {channelFilterFromUrl && ' - '}
              Filtered by encoder:{' '}
              <i>{ALL_ENCODER_LABELS[encoderFilterFromUrl] ?? encoderFilterFromUrl}</i>
            </>
          )}
          {sizeChangeFilterFromUrl && (
            <>
              {(channelFilterFromUrl || encoderFilterFromUrl) && ' - '}
              Filtered by size change: <i>{sizeChangeLabel(sizeChangeFilterFromUrl)}</i>
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

        {actionFailures.length > 0 && (
          <div className="settings-current">
            <p>
              {actionFailures.some(failure => !failure.id)
                ? 'The action failed:'
                : `${actionFailures.length} job(s) could not be updated:`}
            </p>
            <ul>
              {actionFailures.map(failure => (
                <li key={failure.id || failure.error}>
                  {failure.id && `${failure.id}: `}
                  {failure.error}
                </li>
              ))}
            </ul>
            <Button label="Dismiss" onClick={() => setActionFailures([])} />
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
                  onAction={runAction}
                  progress={
                    (job.task_id ? progressByTaskId[job.task_id] : undefined) ??
                    job.progress ??
                    undefined
                  }
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
