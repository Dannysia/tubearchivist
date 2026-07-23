import formatDate from '../functions/formatDates';
import Button from './Button';
import deleteExtractionById from '../api/actions/deleteExtractionById';
import { ExtractionItem } from '../pages/Extraction';

type ExtractionListItemProps = {
  item: ExtractionItem;
  setRefresh: () => void;
};

const buildYoutubeUrl = (item: ExtractionItem) => {
  if (item.item_type === 'video') {
    return `https://www.youtube.com/watch?v=${item.youtube_id}`;
  }
  if (item.item_type === 'playlist') {
    return `https://www.youtube.com/playlist?list=${item.youtube_id}`;
  }
  return `https://www.youtube.com/channel/${item.youtube_id}`;
};

const ExtractionListItem = ({ item, setRefresh }: ExtractionListItemProps) => {
  const isFailed = item.status === 'failed';

  return (
    <div className="video-item list" id={`extraction-${item.id}`}>
      <div className="video-desc list">
        <div>
          <a href={buildYoutubeUrl(item)} target="_blank" rel="noopener noreferrer">
            <h3>{item.youtube_id}</h3>
          </a>
          <span>
            {item.item_type}
            {item.vid_type && ` - ${item.vid_type}`}
          </span>
        </div>

        <p>
          <span>Status: {item.status}</span>
          {' | '}
          <span>Added: {formatDate(item.timestamp * 1000)}</span>
          {item.auto_start && (
            <>
              {' | '}
              <span>auto</span>
            </>
          )}
        </p>

        {isFailed && item.message && (
          <div>
            <p className="danger-zone">{item.message}</p>
          </div>
        )}

        <div className="button-box">
          <Button
            label="Forget"
            className={isFailed ? 'danger-button' : ''}
            onClick={async () => {
              await deleteExtractionById(item.id);
              setRefresh();
            }}
          />
        </div>
      </div>
    </div>
  );
};

export default ExtractionListItem;
