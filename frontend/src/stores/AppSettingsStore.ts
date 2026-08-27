import { create } from 'zustand';
import { AppSettingsConfigType } from '../api/loader/loadAppsettingsConfig';

interface AppSettingsState {
  appSettingsConfig: AppSettingsConfigType;
  setAppSettingsConfig: (appSettingsConfig: AppSettingsConfigType) => void;
}

export const useAppSettingsStore = create<AppSettingsState>(set => ({
  appSettingsConfig: {
    subscriptions: {
      channel_size: null,
      live_channel_size: null,
      shorts_channel_size: null,
      playlist_size: null,
      auto_start: false,
      extract_flat: false,
      frequency_hours: null,
      jitter_percent: null,
    },
    downloads: {
      limit_speed: null,
      sleep_interval: null,
      autodelete_days: null,
      format: null,
      format_sort: null,
      add_metadata: false,
      subtitle: null,
      subtitle_source: null,
      subtitle_index: false,
      comment_max: null,
      comment_sort: 'asc',
      cookie_import: false,
      pot_provider_url: null,
      throttledratelimit: null,
      extractor_lang: null,
      integrate_ryd: false,
      integrate_sponsorblock: false,
      auto_rotate_exit_node: false,
      max_exit_node_rotates: 3,
    },
    application: {
      enable_snapshot: false,
      enable_cast: false,
      downscale_max_concurrent: null,
      downscale_encoder: 'h264',
      downscale_crf: 23,
      downscale_preset: 'veryfast',
      log_retention_days: 7,
    },
  },
  setAppSettingsConfig: appSettingsConfig => set({ appSettingsConfig }),
}));
