import APIClient from '../../functions/APIClient';

export type AppSettingsConfigType = {
  subscriptions: {
    channel_size: number | null;
    live_channel_size: number | null;
    shorts_channel_size: number | null;
    playlist_size: number | null;
    auto_start: boolean;
    extract_flat: boolean;
    frequency_hours: number | null;
    jitter_percent: number | null;
  };
  downloads: {
    limit_speed: number | null;
    sleep_interval: number | null;
    autodelete_days: number | null;
    format: string | null;
    format_sort: string | null;
    add_metadata: boolean;
    subtitle: string | null;
    subtitle_source: string | null;
    subtitle_index: boolean;
    comment_max: string | null;
    comment_sort: string;
    cookie_import: boolean;
    pot_provider_url: string | null;
    throttledratelimit: number | null;
    extractor_lang: string | null;
    integrate_ryd: boolean;
    integrate_sponsorblock: boolean;
  };
  application: {
    enable_snapshot: boolean;
    enable_cast: boolean;
    downscale_max_concurrent: number | null;
    downscale_encoder: 'h264' | 'h264_vaapi' | 'h265' | 'h265_vaapi' | 'av1' | 'av1_vaapi';
    downscale_crf: number;
  };
};

const loadAppsettingsConfig = async () => {
  return APIClient<AppSettingsConfigType>('/api/appsettings/config/');
};

export default loadAppsettingsConfig;
