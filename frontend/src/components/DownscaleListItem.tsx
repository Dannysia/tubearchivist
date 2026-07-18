import { useState } from 'react';
import { Link } from 'react-router-dom';
import Routes from '../configuration/routes/RouteList';
import Button from './Button';
import VideoThumbnail from './VideoThumbail';
import humanFileSize from '../functions/humanFileSize';
import stopTaskByName from '../api/actions/stopTaskByName';
import updateDownscaleQueueByIds from '../api/actions/updateDownscaleQueueByIds';
import { FileSizeUnits } from '../api/actions/updateUserConfig';
import { useUserConfigStore } from '../stores/UserConfigStore';
import { DownscaleJob } from '../pages/Downscale';
import getApiUrl from '../configuration/getApiUrl';
import VideoCompareSlider from './VideoCompareSlider';

type PreviewType = 'original' | 'split' | 'downscaled' | null;

type DownscaleListItemProps = {
  job: DownscaleJob;
  isSelected: boolean;
  onToggle: (id: string) => void;
  setRefresh: () => void;
  progress?: number;
};

const DownscaleListItem = ({
  job,
  isSelected,
  onToggle,
  setRefresh,
  progress,
}: DownscaleListItemProps) => {
  const { userConfig } = useUserConfigStore();
  const useSiUnits = userConfig.file_size_unit === FileSizeUnits.Metric;

  const [preview, setPreview] = useState<PreviewType>(null);

  const isRunning = job.status === 'running';
  const isPendingReview = job.status === 'pending_review';

  const togglePreview = (which: PreviewType) => {
    setPreview(current => (current === which ? null : which));
  };

  return (
    <div className="video-item list" id={`downscale-${job.id}`}>
      <div className="video-thumb-wrap list">
        <div className="video-thumb">
          <VideoThumbnail videoThumbUrl={job.vid_thumb_url} />
          <div className="video-tags">
            <span>{job.status}</span>
          </div>
          {isRunning && (
            <div
              className="video-progress-bar"
              style={{ width: `${(progress ?? 0) * 100}%` }}
            ></div>
          )}
        </div>
      </div>

      <div className="video-desc list">
        <div>
          <Link to={Routes.Video(job.youtube_id)}>
            <h3>{job.title}</h3>
          </Link>
          <span>{job.channel_name}</span>
        </div>

        <p>
          <span>
            {job.current_height}p → {job.target_height}p
          </span>
          {job.original_size > 0 && (
            <span>
              {' '}
              | {humanFileSize(job.original_size, useSiUnits)}
              {job.new_size > 0 && <> → {humanFileSize(job.new_size, useSiUnits)}</>}
            </span>
          )}
        </p>

        {job.message && (
          <div>
            <p className="danger-zone">{job.message}</p>
          </div>
        )}

        {isPendingReview && (
          <div className="button-box">
            <Button
              label="Play Original"
              className={preview === 'original' ? 'active-button' : ''}
              onClick={() => togglePreview('original')}
            />
            <Button
              label="Compare (Split)"
              className={preview === 'split' ? 'active-button' : ''}
              onClick={() => togglePreview('split')}
            />
            <Button
              label="Play Downscaled"
              className={preview === 'downscaled' ? 'active-button' : ''}
              onClick={() => togglePreview('downscaled')}
            />
          </div>
        )}

        {(preview === 'original' || preview === 'downscaled') && (
          <video
            key={preview}
            controls
            autoPlay
            width="100%"
            src={`${getApiUrl()}${preview === 'original' ? job.media_url : job.tmp_file_path}`}
          />
        )}

        {preview === 'split' && (
          <VideoCompareSlider
            originalSrc={`${getApiUrl()}${job.media_url}`}
            newSrc={`${getApiUrl()}${job.tmp_file_path}`}
          />
        )}

        <div>
          {!isRunning && (
            <div className="button-box">
              <input
                type="checkbox"
                checked={isSelected}
                onChange={() => onToggle(job.id)}
                title="select for bulk action"
              />
            </div>
          )}

          {isPendingReview && (
            <>
              <div className="button-box">
                <Button
                  label="Accept"
                  onClick={async () => {
                    await updateDownscaleQueueByIds([job.id], 'accept');
                    setRefresh();
                  }}
                />
              </div>
              <div className="button-box">
                <Button
                  label="Reject"
                  className="danger-button"
                  onClick={async () => {
                    await updateDownscaleQueueByIds([job.id], 'reject');
                    setRefresh();
                  }}
                />
              </div>
            </>
          )}

          {!isPendingReview && !isRunning && (
            <div className="button-box">
              <Button
                label="Dismiss"
                className="danger-button"
                onClick={async () => {
                  await updateDownscaleQueueByIds([job.id], 'reject');
                  setRefresh();
                }}
              />
            </div>
          )}

          {isRunning && (
            <div className="button-box">
              <Button
                label="Cancel"
                className="danger-button"
                onClick={async () => {
                  await stopTaskByName(job.task_id);
                  setRefresh();
                }}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default DownscaleListItem;
