// local encoding only - keys match ENCODER_SETTINGS in
// backend/downscale/src/downscale.py
export const ENCODER_LABELS: Record<string, string> = {
  h264: 'H.264',
  h264_vaapi: 'H.264 (Hardware - VAAPI)',
  h265: 'H.265 (HEVC)',
  h265_vaapi: 'H.265 (Hardware - VAAPI)',
  av1: 'AV1',
  av1_vaapi: 'AV1 (Hardware - VAAPI)',
};

// downscale_crf is CRF, CQP's -qp or ICQ's -global_quality per encoder
export const QUALITY_LABELS: Record<string, string> = {
  h264: 'CRF',
  h265: 'CRF',
  av1: 'CRF',
  h264_vaapi: 'QP',
  h265_vaapi: 'QP',
  av1_vaapi: 'ICQ',
};

// remote workers report their own encoder string: ffmpeg suffixes it
// (av1_nvenc), HandBrake prefixes it (nvenc_av1)
export const NVENC_ENCODER_LABELS: Record<string, string> = {
  h264_nvenc: 'H.264 (Hardware - NVENC)',
  hevc_nvenc: 'H.265 (Hardware - NVENC)',
  av1_nvenc: 'AV1 (Hardware - NVENC)',
  nvenc_h264: 'H.264 (Hardware - NVENC)',
  nvenc_h265: 'H.265 (Hardware - NVENC)',
  nvenc_av1: 'AV1 (Hardware - NVENC)',
};

// constant quality either way - ffmpeg's -cq, HandBrake's -q
export const NVENC_QUALITY_LABELS: Record<string, string> = {
  h264_nvenc: 'CQ',
  hevc_nvenc: 'CQ',
  av1_nvenc: 'CQ',
  nvenc_h264: 'CQ',
  nvenc_h265: 'CQ',
  nvenc_av1: 'CQ',
};

export const ALL_ENCODER_LABELS: Record<string, string> = {
  ...ENCODER_LABELS,
  ...NVENC_ENCODER_LABELS,
};

export const ALL_QUALITY_LABELS: Record<string, string> = {
  ...QUALITY_LABELS,
  ...NVENC_QUALITY_LABELS,
};
