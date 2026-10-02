const togglePlayback = (video: HTMLVideoElement) => {
  if (!video.paused) {
    video.pause();
    return;
  }

  video.play().catch(error => {
    if (error.name !== 'AbortError') {
      console.error(error);
    }
  });
};

export default togglePlayback;
