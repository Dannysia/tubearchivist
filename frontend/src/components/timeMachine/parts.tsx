import { ReactNode, useState } from 'react';
import { Link } from 'react-router-dom';
import { VideoResponseType } from '../../api/loader/loadVideoById';
import Routes from '../../configuration/routes/RouteList';
import VideoThumbnail from '../VideoThumbail';
import ChannelIcon from '../ChannelIcon';
import Linkify from '../Linkify';
import { CommentsType } from '../CommentBox';
import convertStarRating from '../../functions/convertStarRating';
import formatTime from '../../functions/formatTime';
import useIsAdmin from '../../functions/useIsAdmin';
import updateChannelSubscription from '../../api/actions/updateChannelSubscription';
import { YouTubeEra } from '../../functions/youtubeEra';
import { count, relativeAge, shortCount } from '../../functions/timeMachineFormat';

export type EraLayoutProps = {
  era: YouTubeEra;
  video: VideoResponseType;
  player: ReactNode;
  published: string;
  similarVideos?: VideoResponseType[];
  comments?: CommentsType[];
  onTimestampClick: (seconds: number) => void;
  onRefresh: () => void;
};

type Channel = VideoResponseType['channel'];

export const ChannelLink = ({ channel }: { channel: Channel }) => (
  <Link to={Routes.ChannelVideo(channel.channel_id)} className="tm-channel-name">
    {channel.channel_name}
  </Link>
);

export const ChannelAvatar = ({ channel }: { channel: Channel }) => (
  <Link to={Routes.ChannelVideo(channel.channel_id)} className="tm-channel-avatar">
    <ChannelIcon channelId={channel.channel_id} channelThumbUrl={channel.channel_thumb_url} />
  </Link>
);

export const Stars = ({ rating }: { rating: number | undefined }) => {
  const stars = convertStarRating(rating);
  if (!stars.length) {
    return null;
  }

  return (
    <span className="tm-stars" role="img" aria-label={`${rating?.toFixed(1)} out of 5 stars`}>
      {stars.map((star, index) => (
        <span key={index} className={`tm-star tm-star-${star}`} />
      ))}
    </span>
  );
};

export const Sparkbar = ({ likes, dislikes }: { likes: number; dislikes: number }) => {
  const total = likes + dislikes;
  const share = total ? (likes / total) * 100 : 0;

  return (
    <div className="tm-sparkbar">
      <div className="tm-sparkbar-likes" style={{ width: `${share}%` }} />
    </div>
  );
};

export const SubscribeButton = ({
  era,
  channel,
  onRefresh,
}: {
  era: YouTubeEra;
  channel: Channel;
  onRefresh: () => void;
}) => {
  const isAdmin = useIsAdmin();
  const [pending, setPending] = useState(false);
  if (!isAdmin) {
    return null;
  }

  const subscribed = channel.channel_subscribed;

  return (
    <button
      type="button"
      className={`tm-subscribe ${subscribed ? 'is-subscribed' : ''}`}
      disabled={pending}
      onClick={async () => {
        setPending(true);
        try {
          await updateChannelSubscription(channel.channel_id, !subscribed);
          onRefresh();
        } catch (error) {
          console.error(error);
        } finally {
          setPending(false);
        }
      }}
    >
      {subscribed
        ? era === 'material' || era === 'modern'
          ? 'Subscribed'
          : 'Unsubscribe'
        : 'Subscribe'}
      {era === 'material' && !subscribed && ` ${shortCount(channel.channel_subs)}`}
    </button>
  );
};

const SIDE_HEADING: Record<YouTubeEra, string | null> = {
  original: 'Related',
  classic: 'Related Videos',
  refresh: null,
  watch7: 'Up next',
  material: 'Up next',
  modern: null,
};

const SideMeta = ({ era, item }: { era: YouTubeEra; item: VideoResponseType }) => {
  const channelName = item.channel.channel_name;
  const views = item.stats.view_count;

  if (era === 'original') {
    return (
      <>
        <span className="tm-side-duration">{formatTime(item.player.duration)}</span>
        <span className="tm-side-channel">
          From: <span className="tm-side-user">{channelName}</span>
        </span>
        <span className="tm-side-views">Views: {count(views)}</span>
      </>
    );
  }

  if (era === 'classic') {
    return (
      <>
        <span className="tm-side-views">{count(views)} views</span>
        <span className="tm-side-channel">{channelName}</span>
      </>
    );
  }

  if (era === 'refresh' || era === 'watch7') {
    return (
      <>
        <span className="tm-side-channel">
          by {era === 'watch7' ? <strong>{channelName}</strong> : channelName}
        </span>
        <span className="tm-side-views">{count(views)} views</span>
      </>
    );
  }

  return (
    <>
      <span className="tm-side-channel">{channelName}</span>
      <span className="tm-side-views">
        {era === 'modern'
          ? `${shortCount(views)} views • ${relativeAge(item.published)}`
          : `${count(views)} views`}
      </span>
    </>
  );
};

export const SideList = ({
  era,
  videos,
  current,
}: {
  era: YouTubeEra;
  videos?: VideoResponseType[];
  current?: VideoResponseType;
}) => {
  const heading = SIDE_HEADING[era];
  const items = current ? [current, ...(videos ?? [])] : (videos ?? []);

  return (
    <div className="tm-side-list">
      {heading && <h3>{heading}</h3>}
      <div className="tm-side-body">
        {items.map(item => (
          <Link
            key={item.youtube_id}
            to={Routes.Video(item.youtube_id)}
            className={`tm-side-item ${item === current ? 'is-current' : ''}`}
          >
            <span className="tm-side-thumb">
              <VideoThumbnail videoThumbUrl={item.vid_thumb_url} />
              {era !== 'original' && (
                <span className="tm-duration">{formatTime(item.player.duration)}</span>
              )}
            </span>
            <span className="tm-side-text">
              <span className="tm-side-title">{item.title}</span>
              <SideMeta era={era} item={item} />
              {item === current && <span className="tm-now-playing">&lt;&lt; Now Playing</span>}
            </span>
          </Link>
        ))}
      </div>
    </div>
  );
};

const COMMENTS_HEADING: Record<YouTubeEra, (total: string) => string> = {
  original: total => `Text Comments (${total})`,
  classic: total => `Text Comments (${total})`,
  refresh: () => 'Top Comments',
  watch7: total => `All Comments (${total})`,
  material: total => `${total} Comments`,
  modern: total => `${total} Comments`,
};

const CommentLine = ({
  era,
  comment,
  onTimestampClick,
}: {
  era: YouTubeEra;
  comment: CommentsType;
  onTimestampClick: (seconds: number) => void;
}) => {
  const withAvatar = era === 'watch7' || era === 'material' || era === 'modern';
  const replies = comment.comment_replies?.length ?? 0;
  const head = (
    <p className="tm-comment-head">
      <span className="tm-comment-author">{comment.comment_author}</span>{' '}
      <span className="tm-muted">
        {era === 'original' || era === 'classic'
          ? `(${comment.comment_time_text})`
          : comment.comment_time_text}
      </span>
      {era === 'refresh' && comment.comment_likecount > 0 && (
        <span className="tm-comment-likes-inline">{count(comment.comment_likecount)}</span>
      )}
    </p>
  );
  const text = (
    <p className="tm-comment-text">
      <Linkify onTimestampClick={onTimestampClick}>{comment.comment_text}</Linkify>
    </p>
  );

  return (
    <div className="tm-comment">
      {withAvatar && <span className="tm-comment-avatar" aria-hidden="true" />}
      <div>
        {era === 'refresh' ? (
          <>
            {text}
            {head}
          </>
        ) : (
          <>
            {head}
            {text}
          </>
        )}
        {withAvatar && comment.comment_likecount > 0 && (
          <p className="tm-muted">
            {era === 'watch7'
              ? count(comment.comment_likecount)
              : shortCount(comment.comment_likecount)}
          </p>
        )}
        {replies > 0 && (
          <p className="tm-muted tm-comment-replies">
            {era === 'material' || era === 'modern' ? 'View ' : ''}
            {replies} {replies === 1 ? 'reply' : 'replies'}
          </p>
        )}
      </div>
    </div>
  );
};

export const Comments = ({
  era,
  comments,
  total,
  onTimestampClick,
}: {
  era: YouTubeEra;
  comments?: CommentsType[];
  total?: number;
  onTimestampClick: (seconds: number) => void;
}) => (
  <div className="tm-comments tm-card">
    {era === 'original' && <h2 className="tm-section-title">Comments &amp; Responses</h2>}
    <h3>{COMMENTS_HEADING[era](count(total))}</h3>
    {!total && <p className="tm-muted">No comments archived for this video.</p>}
    {comments?.map(comment => (
      <CommentLine
        key={comment.comment_id}
        era={era}
        comment={comment}
        onTimestampClick={onTimestampClick}
      />
    ))}
  </div>
);

const TOGGLE_LABELS: Record<YouTubeEra, [string, string]> = {
  original: ['(more)', '(less)'],
  classic: ['(more info)', '(less info)'],
  refresh: ['Show more', 'Show less'],
  watch7: ['Show more', 'Show less'],
  material: ['Show more', 'Show less'],
  modern: ['...more', 'Show less'],
};

export const Description = ({
  era,
  video,
  published,
  onTimestampClick,
}: {
  era: YouTubeEra;
  video: VideoResponseType;
  published: string;
  onTimestampClick: (seconds: number) => void;
}) => {
  const [expanded, setExpanded] = useState(false);
  const [more, less] = TOGGLE_LABELS[era];

  return (
    <div className={`tm-description tm-card ${expanded ? 'is-expanded' : ''}`}>
      {era === 'refresh' && (
        <p className="tm-uploader">
          Uploaded by <ChannelLink channel={video.channel} /> on {published}
        </p>
      )}
      {era === 'watch7' && <p className="tm-published">Published on {published}</p>}
      {era === 'modern' && (
        <p className="tm-description-stats">
          {count(video.stats.view_count)} views&nbsp;&nbsp;{relativeAge(video.published)}
        </p>
      )}
      <p className="tm-description-text">
        <Linkify onTimestampClick={onTimestampClick}>{video.description}</Linkify>
      </p>
      {video.description && (
        <button
          type="button"
          className="tm-description-toggle"
          aria-expanded={expanded}
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? less : more}
        </button>
      )}
    </div>
  );
};
