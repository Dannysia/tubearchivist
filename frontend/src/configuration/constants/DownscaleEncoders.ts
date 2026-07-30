export type DownscaleEncoderType =
  | 'h264'
  | 'h264_vaapi'
  | 'h265'
  | 'h265_vaapi'
  | 'av1'
  | 'av1_vaapi';

export const ENCODER_LABELS: Record<string, string> = {
  h264: 'H.264',
  h264_vaapi: 'H.264 (Hardware - VAAPI)',
  h265: 'H.265 (HEVC)',
  h265_vaapi: 'H.265 (Hardware - VAAPI)',
  av1: 'AV1',
  av1_vaapi: 'AV1 (Hardware - VAAPI)',
};

// same downscale_crf value drives a different ffmpeg mechanism per encoder:
// real CRF for software, CQP's -qp for h264/h265 hardware, ICQ's
// -global_quality for AV1 hardware (av1_vaapi has no -qp support)
export const QUALITY_LABELS: Record<string, string> = {
  h264: 'CRF',
  h265: 'CRF',
  av1: 'CRF',
  h264_vaapi: 'QP',
  h265_vaapi: 'QP',
  av1_vaapi: 'ICQ',
};
