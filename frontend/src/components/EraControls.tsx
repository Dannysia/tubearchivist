import { KeyboardEvent, useEffect, useState } from 'react';
import formatTime from '../functions/formatTime';
import { YouTubeEra } from '../functions/youtubeEra';
import togglePlayback from '../functions/togglePlayback';

type EraControlsProps = {
  era: YouTubeEra;
  video: HTMLVideoElement | null;
  knownDuration: number;
  onFullscreen: () => void;
};

type PlayerState = {
  paused: boolean;
  currentTime: number;
  duration: number;
  buffered: number;
  volume: number;
  muted: boolean;
  hasCaptions: boolean;
  captionLabel: string;
};

const EMPTY_STATE: PlayerState = {
  paused: true,
  currentTime: 0,
  duration: 0,
  buffered: 0,
  volume: 1,
  muted: false,
  hasCaptions: false,
  captionLabel: '',
};

const readState = (video: HTMLVideoElement): PlayerState => {
  const tracks = [...video.textTracks];
  const buffered = video.buffered.length ? video.buffered.end(video.buffered.length - 1) : 0;

  return {
    paused: video.paused,
    currentTime: video.currentTime,
    duration: Number.isFinite(video.duration) ? video.duration : 0,
    buffered,
    volume: video.volume,
    muted: video.muted,
    hasCaptions: tracks.length > 0,
    captionLabel: tracks.find(track => track.mode === 'showing')?.label ?? '',
  };
};

const VIDEO_EVENTS = [
  'play',
  'pause',
  'timeupdate',
  'durationchange',
  'progress',
  'volumechange',
  'loadedmetadata',
  'seeking',
  'seeked',
];

const isArrowStep = (event: KeyboardEvent) =>
  event.key === 'ArrowLeft' || event.key === 'ArrowRight';

const PlayIcon = () => (
  <svg viewBox="0 0 16 16" aria-hidden="true">
    <path d="M4 2.5v11l9-5.5z" fill="currentColor" />
  </svg>
);

const PauseIcon = () => (
  <svg viewBox="0 0 16 16" aria-hidden="true">
    <path d="M3.5 2.5h3v11h-3zM9.5 2.5h3v11h-3z" fill="currentColor" />
  </svg>
);

const VolumeIcon = ({ muted }: { muted: boolean }) => (
  <svg viewBox="0 0 16 16" aria-hidden="true">
    <path d="M2 6h3l4-3.5v11L5 10H2z" fill="currentColor" />
    {muted ? (
      <path d="M11 6l4 4M15 6l-4 4" stroke="currentColor" strokeWidth="1.5" />
    ) : (
      <path
        d="M11 5.5a3.5 3.5 0 0 1 0 5M12.5 3.5a6 6 0 0 1 0 9"
        stroke="currentColor"
        strokeWidth="1.3"
        fill="none"
      />
    )}
  </svg>
);

const FullscreenIcon = () => (
  <svg viewBox="0 0 16 16" aria-hidden="true">
    <path
      d="M2 6V2h4M10 2h4v4M14 10v4h-4M6 14H2v-4"
      stroke="currentColor"
      strokeWidth="1.6"
      fill="none"
    />
  </svg>
);

const EraControls = ({ era, video, knownDuration, onFullscreen }: EraControlsProps) => {
  const [state, setState] = useState<PlayerState>(EMPTY_STATE);

  useEffect(() => {
    if (!video) {
      return;
    }

    const sync = () => setState(readState(video));
    sync();
    VIDEO_EVENTS.forEach(name => video.addEventListener(name, sync));
    video.textTracks.addEventListener('change', sync);
    video.textTracks.addEventListener('addtrack', sync);

    return () => {
      VIDEO_EVENTS.forEach(name => video.removeEventListener(name, sync));
      video.textTracks.removeEventListener('change', sync);
      video.textTracks.removeEventListener('addtrack', sync);
    };
  }, [video]);

  if (!video) {
    return null;
  }

  const cycleCaptions = () => {
    const tracks = [...video.textTracks];
    const showing = tracks.findIndex(track => track.mode === 'showing');
    if (showing !== -1) {
      tracks[showing].mode = 'hidden';
    }

    const next = tracks[showing + 1];
    if (next) {
      next.mode = 'showing';
    }
  };

  const duration = state.duration || knownDuration;
  const played = duration ? (state.currentTime / duration) * 100 : 0;
  const loaded = duration ? (state.buffered / duration) * 100 : 0;
  const volume = state.muted ? 0 : state.volume;

  const seekBar = (
    <div className="era-seek">
      <div className="era-seek-loaded" style={{ width: `${loaded}%` }} />
      <div className="era-seek-played" style={{ width: `${played}%` }} />
      <span className="era-seek-scrubber" style={{ left: `${played}%` }} />
      <input
        type="range"
        aria-label="Seek"
        aria-valuetext={`${formatTime(state.currentTime)} of ${formatTime(duration)}`}
        min={0}
        max={duration || 0}
        step={0.1}
        value={state.currentTime}
        onKeyDown={event => {
          if (isArrowStep(event)) {
            event.preventDefault();
          }
        }}
        onChange={event => {
          // eslint-disable-next-line react-hooks/immutability
          video.currentTime = Number(event.currentTarget.value);
        }}
      />
    </div>
  );

  const time = (
    <span className="era-time">
      <span className="era-time-current">{formatTime(state.currentTime)}</span>
      <span> / </span>
      <span>{formatTime(duration)}</span>
    </span>
  );

  const volumeControl = (
    <span className="era-volume">
      <button
        type="button"
        aria-label={volume === 0 ? 'Unmute' : 'Mute'}
        onClick={() => {
          if (volume === 0) {
            // eslint-disable-next-line react-hooks/immutability
            video.muted = false;
            video.volume = video.volume || 1;
          } else {
            video.muted = true;
          }
        }}
      >
        <VolumeIcon muted={volume === 0} />
      </button>
      <input
        type="range"
        aria-label="Volume"
        min={0}
        max={1}
        step={0.05}
        value={volume}
        onKeyDown={event => {
          if (isArrowStep(event)) {
            event.stopPropagation();
          }
        }}
        onChange={event => {
          // eslint-disable-next-line react-hooks/immutability
          video.volume = Number(event.currentTarget.value);
          video.muted = false;
        }}
      />
    </span>
  );

  const playButton = (
    <button
      type="button"
      className="era-play"
      aria-label={state.paused ? 'Play' : 'Pause'}
      onClick={() => togglePlayback(video)}
    >
      {state.paused ? <PlayIcon /> : <PauseIcon />}
    </button>
  );

  const captionsButton = state.hasCaptions && (
    <button
      type="button"
      className={`era-cc ${state.captionLabel ? 'is-on' : ''}`}
      aria-label={`Subtitles: ${state.captionLabel || 'off'}`}
      title={`Subtitles: ${state.captionLabel || 'off'}`}
      onClick={cycleCaptions}
    >
      CC
    </button>
  );

  const fullscreenButton = (
    <button type="button" aria-label="Fullscreen" onClick={onFullscreen}>
      <FullscreenIcon />
    </button>
  );

  if (era === 'original' || era === 'classic') {
    return (
      <div className={`era-controls era-controls-single era-controls-${era}`}>
        {playButton}
        {seekBar}
        {time}
        {volumeControl}
        {captionsButton}
        {fullscreenButton}
      </div>
    );
  }

  return (
    <div className={`era-controls era-controls-${era}`}>
      {seekBar}
      <div className="era-controls-row">
        {playButton}
        {volumeControl}
        {time}
        <span className="era-spacer" />
        {captionsButton}
        {fullscreenButton}
      </div>
    </div>
  );
};

export default EraControls;
