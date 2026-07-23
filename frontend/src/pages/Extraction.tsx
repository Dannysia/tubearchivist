import { useEffect, useState } from 'react';
import { useOutletContext, useSearchParams } from 'react-router-dom';
import { Fragment } from 'react/jsx-runtime';
import { OutletContextType } from './Base';
import { ConfigType } from './Home';
import Pagination, { PaginationType } from '../components/Pagination';
import Button from '../components/Button';
import ExtractionListItem from '../components/ExtractionListItem';
import Notifications from '../components/Notifications';
import loadExtractionQueue, {
  ExtractionItemType,
  ExtractionStatus,
} from '../api/loader/loadExtractionQueue';
import deleteExtractionQueueByFilter from '../api/actions/deleteExtractionQueueByFilter';
import updateExtractionQueueByFilter from '../api/actions/updateExtractionQueueByFilter';
import { ApiResponseType } from '../functions/APIClient';

export type ExtractionItem = {
  id: string;
  youtube_id: string;
  item_type: 'video' | 'channel' | 'playlist';
  vid_type?: string;
  limit?: number;
  status: ExtractionStatus;
  message?: string;
  target_status: string;
  auto_start: boolean;
  flat: boolean;
  force: boolean;
  timestamp: number;
};

export type ExtractionResponseType = {
  data?: ExtractionItem[];
  config?: ConfigType;
  paginate?: PaginationType;
};

const Extraction = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const { currentPage, setCurrentPage } = useOutletContext() as OutletContextType;

  const statusFilterFromUrl = searchParams.get('status') as ExtractionStatus | null;
  const itemTypeFilterFromUrl = searchParams.get('item_type') as ExtractionItemType | null;
  const searchInput = searchParams.get('q') || '';

  const [refreshNonce, setRefreshNonce] = useState(0);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [extractionResponse, setExtractionResponse] =
    useState<ApiResponseType<ExtractionResponseType>>();

  const { data: extractionResponseData } = extractionResponse ?? {};
  const itemList = extractionResponseData?.data;
  const pagination = extractionResponseData?.paginate;

  const refreshQueue = () => {
    setRefreshNonce(current => current + 1);
  };

  useEffect(() => {
    (async () => {
      const response = await loadExtractionQueue(
        currentPage,
        statusFilterFromUrl,
        itemTypeFilterFromUrl,
        searchInput,
      );
      setExtractionResponse(response);
    })();
  }, [currentPage, statusFilterFromUrl, itemTypeFilterFromUrl, searchInput, refreshNonce]);

  useEffect(() => {
    const hasActiveItem = itemList?.some(
      item => item.status === 'pending' || item.status === 'extracting',
    );

    if (!hasActiveItem) {
      return;
    }

    const intervalId = setInterval(refreshQueue, 3000);
    return () => clearInterval(intervalId);
  }, [itemList]);

  const handleSetPage = (page: number) => {
    setCurrentPage(page);
  };

  const setFilterParam = (key: string, value: string) => {
    const params = searchParams;
    if (value !== 'all') {
      params.set(key, value);
    } else {
      params.delete(key);
    }
    setSearchParams(params);
  };

  return (
    <>
      <title>TA | Extraction Queue</title>
      <div className="boxed-content">
        <div className="title-bar">
          <h1>Extraction Queue</h1>
        </div>

        <Notifications pageName="download" />

        <div className="view-controls three">
          <select
            name="status_filter"
            id="status_filter"
            value={statusFilterFromUrl || 'all'}
            onChange={event => setFilterParam('status', event.currentTarget.value)}
          >
            <option value="all">all statuses</option>
            <option value="pending">pending</option>
            <option value="extracting">extracting</option>
            <option value="failed">failed</option>
          </select>
          <select
            name="item_type_filter"
            id="item_type_filter"
            value={itemTypeFilterFromUrl || 'all'}
            onChange={event => setFilterParam('item_type', event.currentTarget.value)}
          >
            <option value="all">all types</option>
            <option value="video">video</option>
            <option value="channel">channel</option>
            <option value="playlist">playlist</option>
          </select>
        </div>

        {statusFilterFromUrl === 'failed' && (
          <div className="button-box">
            <Button
              label="Retry Failed"
              onClick={async () => {
                await updateExtractionQueueByFilter('failed', itemTypeFilterFromUrl);
                refreshQueue();
              }}
            />
            {showDeleteConfirm ? (
              <>
                <Button
                  className="danger-button"
                  label="Confirm Forget All"
                  onClick={async () => {
                    await deleteExtractionQueueByFilter('failed', itemTypeFilterFromUrl);
                    setShowDeleteConfirm(false);
                    refreshQueue();
                  }}
                />
                <Button label="Cancel" onClick={() => setShowDeleteConfirm(false)} />
              </>
            ) : (
              <Button
                className="danger-button"
                label="Forget All Failed"
                onClick={() => setShowDeleteConfirm(true)}
              />
            )}
          </div>
        )}

        {itemList?.length === 0 && <p>No items in the extraction queue.</p>}
      </div>

      <div className="boxed-content">
        <div className="video-list list">
          {itemList?.map(item => {
            return (
              <Fragment key={item.id}>
                <ExtractionListItem item={item} setRefresh={refreshQueue} />
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

export default Extraction;
