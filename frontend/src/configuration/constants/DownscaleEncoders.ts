export type DownscaleEncoderType =
  | 'h264'
  | 'h264_vaapi'
  | 'h265'
  | 'h265_vaapi'
  | 'av1'
  | 'av1_vaapi';

// selectable for TA's own local encoding (SettingsApplication.tsx's
// ENCODER_OPTIONS is derived from this) - keys match ENCODER_SETTINGS in
// backend/downscale/src/downscale.py
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

// not locally selectable (no NVENC hardware on the TA host) - a remote
// worker reports its own encoder string as-is (see
// docs/remote-downscale/worker.md), using ffmpeg's actual -c:v names
// rather than TA's internal h264/h265/av1 aliases, hence "hevc_nvenc"
// rather than "h265_nvenc" here. Kept out of ENCODER_LABELS so these
// never show up as options in the local downscale_encoder dropdown.
export const NVENC_ENCODER_LABELS: Record<string, string> = {
  h264_nvenc: 'H.264 (Hardware - NVENC)',
  hevc_nvenc: 'H.265 (Hardware - NVENC)',
  av1_nvenc: 'AV1 (Hardware - NVENC)',
};

// NVENC's constant-quality mode (-rc vbr -cq N -b:v 0, see worker.md)
export const NVENC_QUALITY_LABELS: Record<string, string> = {
  h264_nvenc: 'CQ',
  hevc_nvenc: 'CQ',
  av1_nvenc: 'CQ',
};

// display-only union of local + remote encoders, for anywhere (like the
// video page) that may be showing a job encoded by either
export const ALL_ENCODER_LABELS: Record<string, string> = {
  ...ENCODER_LABELS,
  ...NVENC_ENCODER_LABELS,
};

export const ALL_QUALITY_LABELS: Record<string, string> = {
  ...QUALITY_LABELS,
  ...NVENC_QUALITY_LABELS,
};
