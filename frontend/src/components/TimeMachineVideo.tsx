import { ComponentType, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { VideoResponseType } from '../api/loader/loadVideoById';
import { SponsorBlockType } from '../pages/Video';
import Routes from '../configuration/routes/RouteList';
import VideoPlayer from './VideoPlayer';
import { CommentsType } from './CommentBox';
import { YouTubeEra } from '../functions/youtubeEra';
import { eraDate } from '../functions/timeMachineFormat';
import { EraLayoutProps } from './timeMachine/parts';
import {
  ClassicLayout,
  MaterialLayout,
  ModernLayout,
  OriginalLayout,
  RefreshLayout,
  Watch7Layout,
} from './timeMachine/layouts';
import '../time-machine.css';

const LAYOUTS: Record<YouTubeEra, ComponentType<EraLayoutProps>> = {
  original: OriginalLayout,
  classic: ClassicLayout,
  refresh: RefreshLayout,
  watch7: Watch7Layout,
  material: MaterialLayout,
  modern: ModernLayout,
};

const FIXED_PAGE_WIDTHS: Partial<Record<YouTubeEra, number>> = {
  original: 905,
  classic: 992,
  refresh: 1032,
};

type TimeMachineVideoProps = {
  era: YouTubeEra;
  video: VideoResponseType;
  sponsorBlock?: SponsorBlockType;
  similarVideos?: VideoResponseType[];
  comments?: CommentsType[];
  autoplay: boolean;
  startAt?: number;
  seekToTimestamp?: number;
  setSeekToTimestamp: (timestamp: number | undefined) => void;
  onTimestampClick: (seconds: number) => void;
  onVideoEnd: () => void;
  onRefresh: () => void;
  onExit: () => void;
};

const TimeMachineVideo = ({
  era,
  video,
  sponsorBlock,
  similarVideos,
  comments,
  autoplay,
  startAt,
  seekToTimestamp,
  setSeekToTimestamp,
  onTimestampClick,
  onVideoEnd,
  onRefresh,
  onExit,
}: TimeMachineVideoProps) => {
  const Layout = LAYOUTS[era];

  useEffect(() => {
    const pageWidth = FIXED_PAGE_WIDTHS[era];
    const viewport = document.querySelector('meta[name="viewport"]');
    if (!pageWidth || !viewport) {
      return;
    }

    const previous = viewport.getAttribute('content') ?? '';
    const scale = Math.min(1, window.screen.width / pageWidth).toFixed(3);
    viewport.setAttribute('content', `width=${pageWidth}, initial-scale=${scale}`);

    return () => viewport.setAttribute('content', previous);
  }, [era]);

  const player = (
    <div className="tm-player">
      <VideoPlayer
        video={video}
        sponsorBlock={sponsorBlock}
        autoplay={autoplay}
        startAt={startAt}
        seekToTimestamp={seekToTimestamp}
        setSeekToTimestamp={setSeekToTimestamp}
        onWatchStateChanged={onRefresh}
        onVideoEnd={onVideoEnd}
        embed
        era={era}
      />
    </div>
  );

  return (
    <div className={`tm tm-${era}`}>
      <header className="tm-header">
        <div className="tm-header-inner">
          <Link to={Routes.Home} className="tm-logo">
            <span className="tm-logo-tube">Tube</span>
            <span className="tm-logo-archivist">Archivist</span>
          </Link>
          {(era === 'original' || era === 'classic') && (
            <span className="tm-tagline">Archive Yourself</span>
          )}
          <button type="button" className="tm-exit" onClick={onExit}>
            Back to the present
          </button>
          {era === 'original' && (
            <nav className="tm-tabs">
              <Link to={Routes.Home}>Videos</Link>
              <Link to={Routes.Channels}>Channels</Link>
              <Link to={Routes.Playlists}>Playlists</Link>
            </nav>
          )}
        </div>
      </header>

      <Layout
        key={video.youtube_id}
        era={era}
        video={video}
        player={player}
        published={eraDate(era, video.published)}
        similarVideos={similarVideos}
        comments={comments}
        onTimestampClick={onTimestampClick}
        onRefresh={onRefresh}
      />
    </div>
  );
};

export default TimeMachineVideo;
