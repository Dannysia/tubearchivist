import { Link } from 'react-router-dom';
import Routes from '../../configuration/routes/RouteList';
import { count, shortCount, starRating } from '../../functions/timeMachineFormat';
import {
  ChannelAvatar,
  ChannelLink,
  Comments,
  Description,
  EraLayoutProps,
  SideList,
  Sparkbar,
  Stars,
  SubscribeButton,
} from './parts';

export const OriginalLayout = ({
  era,
  video,
  player,
  published,
  similarVideos,
  comments,
  onTimestampClick,
  onRefresh,
}: EraLayoutProps) => {
  const { channel, stats } = video;

  return (
    <div className="tm-body">
      <h1 className="tm-title">{video.title}</h1>
      <div className="tm-main">
        {player}
        <div className="tm-interact">
          <div className="tm-rating-box">
            <span className="tm-small-label">Rate this video:</span>
            <Stars rating={starRating(stats)} />
            <span className="tm-small">
              {count(stats.like_count + stats.dislike_count)} ratings
            </span>
          </div>
          <div className="tm-stats-row">
            <span>
              <span className="tm-label">Views:</span> {count(stats.view_count)}
            </span>
            <span className="tm-divider">|</span>
            <span>
              <span className="tm-label">Comments:</span> {count(video.comment_count)}
            </span>
          </div>
        </div>
        <Comments
          era={era}
          comments={comments}
          total={video.comment_count}
          onTimestampClick={onTimestampClick}
        />
      </div>
      <aside className="tm-side">
        <div className="tm-about-box">
          <div className="tm-about-head">
            <div>
              <p>
                <span className="tm-label">Added</span> {published}
              </p>
              <p>
                <span className="tm-label">From</span> <ChannelLink channel={channel} />
              </p>
            </div>
            <SubscribeButton era={era} channel={channel} onRefresh={onRefresh} />
          </div>
          <ChannelAvatar channel={channel} />
          <Description
            era={era}
            video={video}
            published={published}
            onTimestampClick={onTimestampClick}
          />
        </div>
        <SideList era={era} videos={similarVideos} current={video} />
      </aside>
    </div>
  );
};

export const ClassicLayout = ({
  era,
  video,
  player,
  published,
  similarVideos,
  comments,
  onTimestampClick,
  onRefresh,
}: EraLayoutProps) => {
  const { channel, stats } = video;

  return (
    <div className="tm-body">
      <div className="tm-main">
        <h1 className="tm-title">{video.title}</h1>
        {player}
        <div className="tm-stats">
          <span className="tm-rating">
            <Stars rating={starRating(stats)} />
            <span className="tm-muted">
              {count(stats.like_count + stats.dislike_count)} ratings
            </span>
          </span>
          <span>
            <strong>{count(stats.view_count)}</strong> views
          </span>
        </div>
        <Comments
          era={era}
          comments={comments}
          total={video.comment_count}
          onTimestampClick={onTimestampClick}
        />
      </div>
      <aside className="tm-side">
        <div className="tm-channel-box">
          <div className="tm-channel-row">
            <ChannelAvatar channel={channel} />
            <div className="tm-channel-meta">
              <ChannelLink channel={channel} />
              <span className="tm-added">{published}</span>
            </div>
            <SubscribeButton era={era} channel={channel} onRefresh={onRefresh} />
          </div>
          <Description
            era={era}
            video={video}
            published={published}
            onTimestampClick={onTimestampClick}
          />
        </div>
        <SideList era={era} videos={similarVideos} />
      </aside>
    </div>
  );
};

export const RefreshLayout = ({
  era,
  video,
  player,
  published,
  similarVideos,
  comments,
  onTimestampClick,
  onRefresh,
}: EraLayoutProps) => {
  const { channel, stats } = video;

  return (
    <div className="tm-body">
      <div className="tm-main">
        <h1 className="tm-title">{video.title}</h1>
        <div className="tm-user-buttons">
          <Link to={Routes.ChannelVideo(channel.channel_id)} className="tm-button">
            {channel.channel_name}
          </Link>
          <SubscribeButton era={era} channel={channel} onRefresh={onRefresh} />
          <span className="tm-button tm-button-static">
            {count(channel.channel_subs)} subscribers
          </span>
        </div>
        {player}
        <div className="tm-actions">
          <a
            className="tm-button"
            href={`https://www.youtube.com/watch?v=${video.youtube_id}`}
            target="_blank"
            rel="noopener noreferrer"
          >
            Share
          </a>
          <span className="tm-views-big">{count(stats.view_count)}</span>
        </div>
        <div className="tm-info">
          <Description
            era={era}
            video={video}
            published={published}
            onTimestampClick={onTimestampClick}
          />
          <div className="tm-likes">
            <Sparkbar likes={stats.like_count} dislikes={stats.dislike_count} />
            <span className="tm-muted tm-small">
              {count(stats.like_count)} likes, {count(stats.dislike_count)} dislikes
            </span>
          </div>
        </div>
        <Comments
          era={era}
          comments={comments}
          total={video.comment_count}
          onTimestampClick={onTimestampClick}
        />
      </div>
      <aside className="tm-side">
        <SideList era={era} videos={similarVideos} />
      </aside>
    </div>
  );
};

export const Watch7Layout = ({
  era,
  video,
  player,
  published,
  similarVideos,
  comments,
  onTimestampClick,
  onRefresh,
}: EraLayoutProps) => {
  const { channel, stats } = video;

  return (
    <div className="tm-body">
      <div className="tm-main">
        {player}
        <div className="tm-headline tm-card">
          <h1 className="tm-title">{video.title}</h1>
          <div className="tm-channel-row">
            <ChannelAvatar channel={channel} />
            <div className="tm-channel-meta">
              <ChannelLink channel={channel} />
              <span className="tm-subscribe-wrap">
                <SubscribeButton era={era} channel={channel} onRefresh={onRefresh} />
                <span className="tm-subscriber-count">{count(channel.channel_subs)}</span>
              </span>
            </div>
          </div>
          <div className="tm-views-info">
            <div className="tm-views-big">{count(stats.view_count)}</div>
            <Sparkbar likes={stats.like_count} dislikes={stats.dislike_count} />
            <div className="tm-muted tm-small tm-like-counts">
              <span className="tm-thumb-up">{count(stats.like_count)}</span>
              <span className="tm-thumb-down">{count(stats.dislike_count)}</span>
            </div>
          </div>
        </div>
        <Description
          era={era}
          video={video}
          published={published}
          onTimestampClick={onTimestampClick}
        />
        <Comments
          era={era}
          comments={comments}
          total={video.comment_count}
          onTimestampClick={onTimestampClick}
        />
      </div>
      <aside className="tm-side">
        <SideList era={era} videos={similarVideos} />
      </aside>
    </div>
  );
};

export const MaterialLayout = ({
  era,
  video,
  player,
  published,
  similarVideos,
  comments,
  onTimestampClick,
  onRefresh,
}: EraLayoutProps) => {
  const { channel, stats } = video;

  return (
    <div className="tm-body">
      <div className="tm-main">
        {player}
        <h1 className="tm-title">{video.title}</h1>
        <div className="tm-stats">
          <span className="tm-muted">{count(stats.view_count)} views</span>
          <span className="tm-sentiment">
            <span className="tm-thumbs">
              <span className="tm-thumb-up">{shortCount(stats.like_count)}</span>
              <span className="tm-thumb-down">{shortCount(stats.dislike_count)}</span>
            </span>
            <Sparkbar likes={stats.like_count} dislikes={stats.dislike_count} />
          </span>
        </div>
        <div className="tm-owner">
          <div className="tm-channel-row">
            <ChannelAvatar channel={channel} />
            <div className="tm-channel-meta">
              <ChannelLink channel={channel} />
              <span className="tm-muted tm-small">Published on {published}</span>
            </div>
            <SubscribeButton era={era} channel={channel} onRefresh={onRefresh} />
          </div>
          <Description
            era={era}
            video={video}
            published={published}
            onTimestampClick={onTimestampClick}
          />
        </div>
        <Comments
          era={era}
          comments={comments}
          total={video.comment_count}
          onTimestampClick={onTimestampClick}
        />
      </div>
      <aside className="tm-side">
        <SideList era={era} videos={similarVideos} />
      </aside>
    </div>
  );
};

export const ModernLayout = ({
  era,
  video,
  player,
  published,
  similarVideos,
  comments,
  onTimestampClick,
  onRefresh,
}: EraLayoutProps) => {
  const { channel, stats } = video;

  return (
    <div className="tm-body">
      <div className="tm-main">
        {player}
        <h1 className="tm-title">{video.title}</h1>
        <div className="tm-owner-row">
          <div className="tm-channel-row">
            <ChannelAvatar channel={channel} />
            <div className="tm-channel-meta">
              <ChannelLink channel={channel} />
              <span className="tm-muted tm-small">
                {shortCount(channel.channel_subs)} subscribers
              </span>
            </div>
            <SubscribeButton era={era} channel={channel} onRefresh={onRefresh} />
          </div>
          <span className="tm-like-pill">
            <span className="tm-thumb-up">{shortCount(stats.like_count)}</span>
            <span className="tm-thumb-down" />
          </span>
        </div>
        <Description
          era={era}
          video={video}
          published={published}
          onTimestampClick={onTimestampClick}
        />
        <Comments
          era={era}
          comments={comments}
          total={video.comment_count}
          onTimestampClick={onTimestampClick}
        />
      </div>
      <aside className="tm-side">
        <SideList era={era} videos={similarVideos} />
      </aside>
    </div>
  );
};
