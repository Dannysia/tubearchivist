import { useEffect, useRef, useState } from 'react';
import Button from './Button';
import formatTime from '../functions/formatTime';

type VideoCompareSliderProps = {
  originalSrc: string;
  newSrc: string;
};

const SYNC_THRESHOLD_SECONDS = 0.3;

const getClientX = (event: MouseEvent | TouchEvent) => {
  return 'touches' in event ? event.touches[0].clientX : event.clientX;
};

const VideoCompareSlider = ({ originalSrc, newSrc }: VideoCompareSliderProps) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const originalRef = useRef<HTMLVideoElement>(null);
  const newRef = useRef<HTMLVideoElement>(null);
  const isDraggingRef = useRef(false);

  const [dividerPercent, setDividerPercent] = useState(50);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);

  const updateDividerFromClientX = (clientX: number) => {
    const container = containerRef.current;
    if (!container) return;

    const rect = container.getBoundingClientRect();
    const percent = ((clientX - rect.left) / rect.width) * 100;
    setDividerPercent(Math.min(100, Math.max(0, percent)));
  };

  useEffect(() => {
    const handleMove = (event: MouseEvent | TouchEvent) => {
      if (!isDraggingRef.current) return;
      updateDividerFromClientX(getClientX(event));
    };

    const handleUp = () => {
      isDraggingRef.current = false;
    };

    window.addEventListener('mousemove', handleMove);
    window.addEventListener('touchmove', handleMove);
    window.addEventListener('mouseup', handleUp);
    window.addEventListener('touchend', handleUp);

    return () => {
      window.removeEventListener('mousemove', handleMove);
      window.removeEventListener('touchmove', handleMove);
      window.removeEventListener('mouseup', handleUp);
      window.removeEventListener('touchend', handleUp);
    };
  }, []);

  const syncNewVideo = () => {
    const original = originalRef.current;
    const newVideo = newRef.current;
    if (!original || !newVideo) return;

    if (Math.abs(newVideo.currentTime - original.currentTime) > SYNC_THRESHOLD_SECONDS) {
      newVideo.currentTime = original.currentTime;
    }
  };

  const togglePlay = () => {
    const original = originalRef.current;
    if (!original) return;

    if (original.paused) {
      original.play();
    } else {
      original.pause();
    }
  };

  const handleSeek = (seconds: number) => {
    if (originalRef.current) originalRef.current.currentTime = seconds;
    if (newRef.current) newRef.current.currentTime = seconds;
    setCurrentTime(seconds);
  };

  return (
    <div className="video-compare-wrap">
      <div
        ref={containerRef}
        className="video-compare"
        onMouseDown={event => {
          isDraggingRef.current = true;
          updateDividerFromClientX(event.clientX);
        }}
        onTouchStart={event => {
          isDraggingRef.current = true;
          updateDividerFromClientX(event.touches[0].clientX);
        }}
      >
        <video
          ref={originalRef}
          src={originalSrc}
          className="video-compare-layer"
          playsInline
          autoPlay
          onPlay={() => {
            setIsPlaying(true);
            newRef.current?.play();
          }}
          onPause={() => {
            setIsPlaying(false);
            newRef.current?.pause();
          }}
          onLoadedMetadata={() => setDuration(originalRef.current?.duration ?? 0)}
          onTimeUpdate={() => {
            setCurrentTime(originalRef.current?.currentTime ?? 0);
            syncNewVideo();
          }}
        />
        <video
          ref={newRef}
          src={newSrc}
          className="video-compare-layer"
          style={{ clipPath: `inset(0 0 0 ${dividerPercent}%)` }}
          muted
          playsInline
        />
        <div
          className="video-compare-divider"
          style={{ left: `${dividerPercent}%` }}
          onMouseDown={event => {
            event.stopPropagation();
            isDraggingRef.current = true;
          }}
          onTouchStart={event => {
            event.stopPropagation();
            isDraggingRef.current = true;
          }}
        />
        <span className="video-compare-label video-compare-label-left">Original</span>
        <span className="video-compare-label video-compare-label-right">Downscaled</span>
      </div>

      <div className="video-compare-controls">
        <Button label={isPlaying ? 'Pause' : 'Play'} onClick={togglePlay} />
        <input
          type="range"
          min={0}
          max={duration || 0}
          step={0.1}
          value={currentTime}
          onChange={event => handleSeek(Number(event.target.value))}
        />
        <span>
          {formatTime(currentTime)} / {formatTime(duration)}
        </span>
      </div>
    </div>
  );
};

export default VideoCompareSlider;
