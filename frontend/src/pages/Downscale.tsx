import { useEffect, useState } from 'react';
import { useOutletContext, useSearchParams } from 'react-router-dom';
import { Fragment } from 'react/jsx-runtime';
import { OutletContextType } from './Base';
import { ConfigType } from './Home';
import Pagination, { PaginationType } from '../components/Pagination';
import Button from '../components/Button';
import DownscaleListItem from '../components/DownscaleListItem';
import loadDownscaleQueue, { DownscaleStatus } from '../api/loader/loadDownscaleQueue';
import updateDownscaleQueueByIds from '../api/actions/updateDownscaleQueueByIds';
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

  const [refreshNonce, setRefreshNonce] = useState(0);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [downscaleResponse, setDownscaleResponse] =
    useState<ApiResponseType<DownscaleResponseType>>();
  const [progressByTaskId, setProgressByTaskId] = useState<Record<string, number>>({});

  const { data: downscaleResponseData } = downscaleResponse ?? {};
  const jobList = downscaleResponseData?.data;
  const pagination = downscaleResponseData?.paginate;

  const hasRunningJob = jobList?.some(job => job.status === 'running') ?? false;

  const refreshQueue = () => {
    setRefreshNonce(current => current + 1);
  };

  useEffect(() => {
    (async () => {
      const response = await loadDownscaleQueue(currentPage, statusFilterFromUrl);
      setDownscaleResponse(response);
    })();
  }, [currentPage, statusFilterFromUrl, refreshNonce]);

  useEffect(() => {
    if (!hasRunningJob) {
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
  }, [hasRunningJob]);

  const handleSetPage = (page: number) => {
    setSelectedIds(new Set());
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

  const handleBulkAction = async (action: 'accept' | 'reject') => {
    await updateDownscaleQueueByIds([...selectedIds], action);
    setSelectedIds(new Set());
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
            }}
          >
            <option value="all">all statuses</option>
            <option value="running">running</option>
            <option value="pending_review">pending review</option>
            <option value="failed">failed</option>
            <option value="cancelled">cancelled</option>
          </select>
        </div>

        {selectedIds.size > 0 && (
          <div className="button-box">
            <Button
              label={`Accept Selected (${selectedIds.size})`}
              onClick={() => handleBulkAction('accept')}
            />
            <Button
              label={`Reject Selected (${selectedIds.size})`}
              className="danger-button"
              onClick={() => handleBulkAction('reject')}
            />
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
