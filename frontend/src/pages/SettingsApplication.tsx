import { useEffect, useState } from 'react';
import loadSnapshots, { SnapshotListType } from '../api/loader/loadSnapshots';
import Notifications from '../components/Notifications';
import PaginationDummy from '../components/PaginationDummy';
import SettingsNavigation from '../components/SettingsNavigation';
import restoreSnapshot from '../api/actions/restoreSnapshot';
import queueSnapshot from '../api/actions/queueSnapshot';
// import updateCookie, { ValidatedCookieType } from '../api/actions/updateCookie';
import deleteApiToken from '../api/actions/deleteApiToken';
import Button from '../components/Button';
import loadAppsettingsConfig, { AppSettingsConfigType } from '../api/loader/loadAppsettingsConfig';
import updateAppsettingsConfig from '../api/actions/updateAppsettingsConfig';
import loadApiToken from '../api/loader/loadApiToken';
import InputConfig from '../components/InputConfig';
import ToggleConfig from '../components/ToggleConfig';
import updateCookie from '../api/actions/updateCookie';
import loadCookie, { CookieStateType } from '../api/loader/loadCookie';
import deleteCookie from '../api/actions/deleteCookie';
import validateCookie from '../api/actions/validateCookie';
import { useUserConfigStore } from '../stores/UserConfigStore';
import MembershipAppsettings from '../components/MembershipAppsettings';
import testDownscaleEncoders, {
  DownscaleEncoderTestResultType,
} from '../api/actions/testDownscaleEncoders';
import LoadingIndicator from '../components/LoadingIndicator';
import { ENCODER_LABELS, QUALITY_LABELS } from '../configuration/constants/DownscaleEncoders';

const ENCODER_OPTIONS = Object.entries(ENCODER_LABELS).map(([value, label]) => ({
  value,
  label,
}));

const PRESET_OPTIONS = [
  'ultrafast',
  'superfast',
  'veryfast',
  'faster',
  'fast',
  'medium',
  'slow',
  'slower',
  'veryslow',
  'placebo',
];

type PresetReferenceRow = { preset: string; time: string; size: string };

// ballpark figures from commonly cited community encoder benchmarks, all
// relative to that codec's own "medium" preset. Not measured on this
// device - actual results depend heavily on source content, resolution
// and hardware, so treat these as a rough sense of direction only.
const PRESET_REFERENCE: Record<'h264' | 'h265' | 'av1' | 'h264_vaapi', PresetReferenceRow[]> = {
  h264: [
    { preset: 'ultrafast', time: '~0.3x (3x faster)', size: '~40-50% larger' },
    { preset: 'superfast', time: '~0.45x', size: '~25-35% larger' },
    { preset: 'veryfast', time: '~0.6x', size: '~10-20% larger' },
    { preset: 'faster', time: '~0.8x', size: '~4-8% larger' },
    { preset: 'fast', time: '~0.9x', size: '~2-4% larger' },
    { preset: 'medium', time: '1x (baseline)', size: 'baseline' },
    { preset: 'slow', time: '~1.6-1.8x', size: '~3-7% smaller' },
    { preset: 'slower', time: '~2.5-3x', size: '~6-10% smaller' },
    { preset: 'veryslow', time: '~4-5x', size: '~8-12% smaller' },
    { preset: 'placebo', time: '~15-30x+', size: '~9-13% smaller' },
  ],
  h265: [
    { preset: 'ultrafast', time: '~0.35x (2-3x faster)', size: '~35-45% larger' },
    { preset: 'superfast', time: '~0.5x', size: '~20-30% larger' },
    { preset: 'veryfast', time: '~0.65x', size: '~8-15% larger' },
    { preset: 'faster', time: '~0.8x', size: '~3-6% larger' },
    { preset: 'fast', time: '~0.9x', size: '~1-3% larger' },
    { preset: 'medium', time: '1x (baseline)', size: 'baseline' },
    { preset: 'slow', time: '~1.8-2.2x', size: '~2-5% smaller' },
    { preset: 'slower', time: '~3-4x', size: '~4-7% smaller' },
    { preset: 'veryslow', time: '~5-7x', size: '~6-9% smaller' },
    { preset: 'placebo', time: '~20x+', size: '~6-10% smaller' },
  ],
  av1: [
    { preset: 'ultrafast', time: '~0.2x (5x faster)', size: '~50-70% larger' },
    { preset: 'superfast', time: '~0.35x', size: '~30-45% larger' },
    { preset: 'veryfast', time: '~0.5x', size: '~15-25% larger' },
    { preset: 'faster', time: '~0.65x', size: '~8-14% larger' },
    { preset: 'fast', time: '~0.8x', size: '~3-6% larger' },
    { preset: 'medium', time: '1x (baseline)', size: 'baseline' },
    { preset: 'slow', time: '~2-2.5x', size: '~5-10% smaller' },
    { preset: 'slower', time: '~3-4x', size: '~8-14% smaller' },
    { preset: 'veryslow', time: '~5-8x', size: '~10-16% smaller' },
    { preset: 'placebo', time: '~10-15x+', size: '~12-18% smaller' },
  ],
  // Quick Sync's Target Usage knob covers a much narrower speed/quality
  // range than software presets - this is much fuzzier community knowledge
  // than the x264 numbers above, not a well-established benchmark chart.
  // ultrafast/superfast share a Target Usage level, as do veryslow/placebo.
  h264_vaapi: [
    { preset: 'ultrafast', time: '~0.5x', size: '~15-20% larger' },
    { preset: 'superfast', time: '~0.5x', size: '~15-20% larger' },
    { preset: 'veryfast', time: '~0.65x', size: '~8-12% larger' },
    { preset: 'faster', time: '~0.8x', size: '~3-6% larger' },
    { preset: 'fast', time: '~0.8x', size: '~3-6% larger' },
    { preset: 'medium', time: '1x (baseline)', size: 'baseline' },
    { preset: 'slow', time: '~1.3x', size: '~3-6% smaller' },
    { preset: 'slower', time: '~1.6x', size: '~5-9% smaller' },
    { preset: 'veryslow', time: '~2x', size: '~8-12% smaller' },
    { preset: 'placebo', time: '~2x', size: '~8-12% smaller' },
  ],
};

type SettingsApplicationReponses = {
  snapshots?: SnapshotListType;
  appSettingsConfig?: AppSettingsConfigType;
  apiToken?: string;
  cookieState?: CookieStateType;
};

const SettingsApplication = () => {
  const { userConfig } = useUserConfigStore();
  const [response, setResponse] = useState<SettingsApplicationReponses>();
  const [refresh, setRefresh] = useState(false);
  const [visibleSnapshotCount, setVisibleSnapshotCount] = useState(10);

  const snapshots = response?.snapshots;
  const appSettingsConfig = response?.appSettingsConfig;
  const apiToken = response?.apiToken;

  // Subscriptions
  const [videoPageSize, setVideoPageSize] = useState<number | null>(null);
  const [livePageSize, setLivePageSize] = useState<number | null>(null);
  const [shortPageSize, setShortPageSize] = useState<number | null>(null);
  const [playlistPageSize, setPlaylistPageSize] = useState<number | null>(null);
  const [isAutostart, setIsAutostart] = useState<boolean>(false);
  const [isExtractFlat, setIsExtractFlat] = useState<boolean>(false);
  const [frequencyHours, setFrequencyHours] = useState<number | null>(null);
  const [jitterPercent, setJitterPercent] = useState<number | null>(null);

  // Downloads
  const [currentDownloadSpeed, setCurrentDownloadSpeed] = useState<number | null>(null);
  const [currentThrottledRate, setCurrentThrottledRate] = useState<number | null>(null);
  const [currentScrapingSleep, setCurrentScrapingSleep] = useState<number | null>(null);
  const [currentAutodelete, setCurrentAutodelete] = useState<number | null>(null);

  // Download Format
  const [downloadsFormat, setDownloadsFormat] = useState<string | null>(null);
  const [downloadsFormatSort, setDownloadsFormatSort] = useState<string | null>(null);
  const [downloadsExtractorLang, setDownloadsExtractorLang] = useState<string | null>(null);
  const [embedMetadata, setEmbedMetadata] = useState(false);

  // Subtitles
  const [subtitleLang, setSubtitleLang] = useState<string | null>(null);
  const [subtitleSource, setSubtitleSource] = useState<string | null>(null);
  const [indexSubtitles, setIndexSubtitles] = useState(false);

  // Comments
  const [commentsMax, setCommentsMax] = useState<string | null>(null);
  const [commentsSort, setCommentsSort] = useState<string>('');

  // Cookie
  const [cookieFormData, setCookieFormData] = useState<string>('');
  const [showCookieForm, setShowCookieForm] = useState<boolean>(false);
  const [potProviderUrl, setPotProviderUrl] = useState<string | null>(null);

  // Integrations
  const [showApiToken, setShowApiToken] = useState(false);
  const [downloadDislikes, setDownloadDislikes] = useState(false);
  const [enableSponsorBlock, setEnableSponsorBlock] = useState(false);
  const [enableCast, setEnableCast] = useState(false);

  // Downscale
  const [downscaleMaxConcurrent, setDownscaleMaxConcurrent] = useState<number | null>(null);
  const [downscaleEncoder, setDownscaleEncoder] = useState('h264');
  const [downscaleCrf, setDownscaleCrf] = useState<number | null>(null);
  const [downscalePreset, setDownscalePreset] = useState('veryfast');
  const [encoderTestResults, setEncoderTestResults] = useState<DownscaleEncoderTestResultType[]>(
    [],
  );
  const [isTestingEncoders, setIsTestingEncoders] = useState(false);

  const isHardwareEncoder = downscaleEncoder.endsWith('_vaapi');
  const codecFamily = downscaleEncoder.replace('_vaapi', '') as 'h264' | 'h265' | 'av1';
  // h264_vaapi has a real speed/quality knob (ffmpeg's -quality, Intel's
  // "Target Usage"); h265_vaapi/av1_vaapi expose nothing equivalent
  const presetUnsupported = isHardwareEncoder && downscaleEncoder !== 'h264_vaapi';
  const presetTableRows = presetUnsupported ? undefined : PRESET_REFERENCE[downscaleEncoder as 'h264' | 'h265' | 'av1' | 'h264_vaapi'];

  // Snapshots
  const [enableSnapshots, setEnableSnapshots] = useState(false);
  const [isSnapshotQueued, setIsSnapshotQueued] = useState(false);
  const [restoringSnapshot, setRestoringSnapshot] = useState(false);

  const fetchData = async () => {
    const snapshotResponse = await loadSnapshots();
    const appSettingsConfig = await loadAppsettingsConfig();
    const apiTokenResponse = await loadApiToken();
    const cookieStateResponse = await loadCookie();

    const { data: snapshotResponseData } = snapshotResponse ?? {};
    const { data: appSettingsConfigData } = appSettingsConfig ?? {};
    const { data: apiTokenResponseData } = apiTokenResponse ?? {};
    const { data: cookieStateResponseData } = cookieStateResponse ?? {};

    // Subscriptions
    setVideoPageSize(appSettingsConfigData?.subscriptions.channel_size ?? null);
    setLivePageSize(appSettingsConfigData?.subscriptions.live_channel_size ?? null);
    setShortPageSize(appSettingsConfigData?.subscriptions.shorts_channel_size ?? null);
    setPlaylistPageSize(appSettingsConfigData?.subscriptions.playlist_size || null);
    setIsAutostart(appSettingsConfigData?.subscriptions.auto_start || false);
    setIsExtractFlat(appSettingsConfigData?.subscriptions.extract_flat || false);
    setFrequencyHours(appSettingsConfigData?.subscriptions.frequency_hours ?? null);
    setJitterPercent(appSettingsConfigData?.subscriptions.jitter_percent ?? null);

    // Downloads
    setCurrentDownloadSpeed(appSettingsConfigData?.downloads.limit_speed || null);
    setCurrentThrottledRate(appSettingsConfigData?.downloads.throttledratelimit || null);
    setCurrentScrapingSleep(appSettingsConfigData?.downloads.sleep_interval || null);
    setCurrentAutodelete(appSettingsConfigData?.downloads.autodelete_days || null);

    // Download Format
    setDownloadsFormat(appSettingsConfigData?.downloads.format || null);
    setDownloadsFormatSort(appSettingsConfigData?.downloads.format_sort || null);
    setDownloadsExtractorLang(appSettingsConfigData?.downloads.extractor_lang || null);
    setEmbedMetadata(appSettingsConfigData?.downloads.add_metadata || false);

    // Subtitles
    setSubtitleLang(appSettingsConfigData?.downloads.subtitle || null);
    setSubtitleSource(appSettingsConfigData?.downloads.subtitle_source || null);
    setIndexSubtitles(appSettingsConfigData?.downloads.subtitle_index || false);

    // Comments
    setCommentsMax(appSettingsConfigData?.downloads.comment_max || null);
    setCommentsSort(appSettingsConfigData?.downloads.comment_sort || '');

    // Cookie
    setPotProviderUrl(appSettingsConfigData?.downloads.pot_provider_url || null);

    // Integrations
    setDownloadDislikes(appSettingsConfigData?.downloads.integrate_ryd || false);
    setEnableSponsorBlock(appSettingsConfigData?.downloads.integrate_sponsorblock || false);
    setEnableCast(appSettingsConfigData?.application.enable_cast || false);

    // Downscale
    setDownscaleMaxConcurrent(appSettingsConfigData?.application.downscale_max_concurrent || null);
    setDownscaleEncoder(appSettingsConfigData?.application.downscale_encoder || 'h264');
    setDownscaleCrf(appSettingsConfigData?.application.downscale_crf ?? null);
    setDownscalePreset(appSettingsConfigData?.application.downscale_preset || 'veryfast');

    // Snapshots
    setEnableSnapshots(appSettingsConfigData?.application.enable_snapshot || false);

    setResponse({
      snapshots: snapshotResponseData,
      appSettingsConfig: appSettingsConfigData,
      apiToken: apiTokenResponseData?.token,
      cookieState: cookieStateResponseData,
    });
  };

  const handleUpdateConfig = async (
    configKey: string,
    configValue: string | boolean | number | null,
  ) => {
    const [group, key] = configKey.split('.');
    const updatedConfig = { [group]: { [key]: configValue } } as Partial<AppSettingsConfigType>;
    await updateAppsettingsConfig(updatedConfig);
    setRefresh(true);
  };

  const handleTestEncoders = async () => {
    setIsTestingEncoders(true);
    setEncoderTestResults([]);
    const response = await testDownscaleEncoders();
    setEncoderTestResults(response?.data ?? []);
    setIsTestingEncoders(false);
  };

  const handleCookieUpdate = async () => {
    await updateCookie(cookieFormData);
    setCookieFormData('');
    setShowCookieForm(false);
    setRefresh(true);
  };

  const handleCookieRevoke = async () => {
    await deleteCookie();
    setRefresh(true);
  };

  const handleCookieValidate = async () => {
    await validateCookie();
    setRefresh(true);
  };

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    fetchData();
  }, []);

  useEffect(() => {
    if (refresh) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      fetchData();
      setRefresh(false);
    }
  }, [refresh]);

  return (
    <>
      <title>TA | Application Settings</title>
      <div className="boxed-content">
        <SettingsNavigation />
        <Notifications pageName={'all'} />

        <div className="title-bar">
          <h1>Application Configurations</h1>
        </div>
        {appSettingsConfig && (
          <div className="info-box">
            <div className="info-box-item">
              <h2 id="subscriptions">Subscription Scan</h2>
              {userConfig.show_help_text && (
                <div className="help-text">
                  <p>Configure how a subscription Scan tracks videos.</p>
                  <ul>
                    <li>The pagesize configures how many videos are checked.</li>
                    <li>Max recommended page size is 50.</li>
                    <li>Disable shorts or streams by setting their page size to 0 (zero).</li>
                    <li>
                      Autostart automatically starts downloading videos from subscriptions with
                      priority.
                    </li>
                    <li>
                      Fast add extracts and adds videos in bulk. That is much faster but is not able
                      to extract as much metadata during adding to the queue.
                    </li>
                    <li>
                      Each subscription is checked independently on its own schedule. Rescan
                      frequency is the average interval between checks; rescan jitter randomizes it
                      &plusmn; that percent per subscription, so they don&apos;t all get checked in
                      one burst.
                    </li>
                  </ul>
                </div>
              )}
              <div className="settings-box-wrapper">
                <div>
                  <p>Videos page size</p>
                </div>
                <InputConfig
                  type="number"
                  name="subscriptions.channel_size"
                  value={videoPageSize}
                  setValue={setVideoPageSize}
                  oldValue={appSettingsConfig?.subscriptions.channel_size}
                  updateCallback={handleUpdateConfig}
                />
              </div>
              <div className="settings-box-wrapper">
                <div>
                  <p>Live Streams page size</p>
                </div>
                <InputConfig
                  type="number"
                  name="subscriptions.live_channel_size"
                  value={livePageSize}
                  setValue={setLivePageSize}
                  oldValue={appSettingsConfig?.subscriptions.live_channel_size}
                  updateCallback={handleUpdateConfig}
                />
              </div>
              <div className="settings-box-wrapper">
                <div>
                  <p>Shorts page size</p>
                </div>
                <InputConfig
                  type="number"
                  name="subscriptions.shorts_channel_size"
                  value={shortPageSize}
                  setValue={setShortPageSize}
                  oldValue={appSettingsConfig?.subscriptions.shorts_channel_size}
                  updateCallback={handleUpdateConfig}
                />
              </div>
              <div className="settings-box-wrapper">
                <div>
                  <p>Playlist page size</p>
                </div>
                <InputConfig
                  type="number"
                  name="subscriptions.playlist_size"
                  value={playlistPageSize}
                  setValue={setPlaylistPageSize}
                  oldValue={appSettingsConfig?.subscriptions.playlist_size}
                  updateCallback={handleUpdateConfig}
                />
              </div>
              <div className="settings-box-wrapper">
                <div>
                  <p>Autostart download subscriptions</p>
                </div>
                <ToggleConfig
                  name="subscriptions.auto_start"
                  value={isAutostart}
                  updateCallback={handleUpdateConfig}
                />
              </div>
              <div className="settings-box-wrapper">
                <div>
                  <p>Fast add</p>
                </div>
                <ToggleConfig
                  name="subscriptions.extract_flat"
                  value={isExtractFlat}
                  updateCallback={handleUpdateConfig}
                />
              </div>
              <div className="settings-box-wrapper">
                <div>
                  <p>Rescan frequency, in hours</p>
                </div>
                <InputConfig
                  type="number"
                  name="subscriptions.frequency_hours"
                  value={frequencyHours}
                  setValue={setFrequencyHours}
                  oldValue={appSettingsConfig?.subscriptions.frequency_hours}
                  updateCallback={handleUpdateConfig}
                />
              </div>
              <div className="settings-box-wrapper">
                <div>
                  <p>Rescan jitter, in percent</p>
                </div>
                <InputConfig
                  type="number"
                  name="subscriptions.jitter_percent"
                  value={jitterPercent}
                  setValue={setJitterPercent}
                  oldValue={appSettingsConfig?.subscriptions.jitter_percent}
                  updateCallback={handleUpdateConfig}
                />
              </div>
            </div>
            <div className="info-box-item">
              <h2 id="downloads">Downloads</h2>
              {userConfig.show_help_text && (
                <div className="help-text">
                  <ul>
                    <li>
                      Limit download speed, in KB/s. Can be helpful to avoid getting blocked by YT.
                    </li>
                    <li>
                      Throttle rate limit restarts a download if the speed falls below the defined
                      limit.
                    </li>
                    <li>
                      The sleep interval slows down requests to YT.
                      <ul>
                        <li>That reduces the likelihood of getting blocked by YT.</li>
                        <li>
                          The number in seconds is randomized +/- 50% from the value you enter.
                        </li>
                        <li>Minimal recommended is 10.</li>
                      </ul>
                    </li>
                    <li>
                      Auto delete deletes videos marked as watched after x days.
                      <ul>
                        <li>The cleanup task triggers after the download finishes.</li>
                        <li>Can also be configured on a per channel basis.</li>
                      </ul>
                    </li>
                  </ul>
                </div>
              )}
              <div className="settings-box-wrapper">
                <div>
                  <p>Download Speed limit</p>
                </div>
                <InputConfig
                  type="number"
                  name="downloads.limit_speed"
                  value={currentDownloadSpeed}
                  setValue={setCurrentDownloadSpeed}
                  oldValue={appSettingsConfig.downloads.limit_speed}
                  updateCallback={handleUpdateConfig}
                />
              </div>
              <div className="settings-box-wrapper">
                <div>
                  <p>Throttled rate limit</p>
                </div>
                <InputConfig
                  type="number"
                  name="downloads.throttledratelimit"
                  value={currentThrottledRate}
                  setValue={setCurrentThrottledRate}
                  oldValue={appSettingsConfig.downloads.throttledratelimit}
                  updateCallback={handleUpdateConfig}
                />
              </div>
              <div className="settings-box-wrapper">
                <div>
                  <p>Sleep interval</p>
                </div>
                <InputConfig
                  type="number"
                  name="downloads.sleep_interval"
                  value={currentScrapingSleep}
                  setValue={setCurrentScrapingSleep}
                  oldValue={appSettingsConfig?.downloads.sleep_interval}
                  updateCallback={handleUpdateConfig}
                />
              </div>
              <div className="settings-box-wrapper">
                <div>
                  <p>
                    <span className="danger-zone">Danger Zone</span>: Auto delete watched
                  </p>
                </div>
                <InputConfig
                  type="number"
                  name="downloads.autodelete_days"
                  value={currentAutodelete}
                  setValue={setCurrentAutodelete}
                  oldValue={appSettingsConfig?.downloads.autodelete_days}
                  updateCallback={handleUpdateConfig}
                />
              </div>
            </div>
            <div className="info-box-item">
              <h2 id="format">Download Format</h2>
              {userConfig.show_help_text && (
                <div className="help-text">
                  <ul>
                    <li>
                      The download format is equivalent to <i>-f</i> yt-dlp argument. Examples:
                      <ul>
                        <li>
                          <span className="settings-current">
                            {'bestvideo[height<=720]+bestaudio/best[height<=720]'}
                          </span>
                          : <q>best</q> video and <q>best</q> audio (yt-dlp's choice), max video
                          height of 720p.
                        </li>
                        <li>
                          <span className="settings-current">
                            {'bestvideo[height<=1080]+bestaudio/best[height<=1080]'}
                          </span>
                          : <q>best</q> video and <q>best</q> audio (yt-dlp's choice), max video
                          height of 1080p.
                        </li>
                        <li>
                          <span className="settings-current">
                            {'bestvideo[height<=1080][vcodec*=avc1]+bestaudio[acodec*=mp4a]/mp4'}
                          </span>
                          : <q>best</q> universally iOS-compatible video (forced avc1) and{' '}
                          <q>best</q> audio (forced mp4a), mp4 container, max video height of 1080p.
                        </li>
                        <li>
                          <span className="settings-current">
                            'bv*[vcodec~=av01]+ba[acodec~=mp4a]/bv*[vcodec~=av01]+ba/
                            bv*[vcodec~=avc1]+ba[acodec~=mp4a]/bv*[vcodec~=avc1]+ba/bv*+ba/b'
                          </span>
                          : <q>best</q> iOS-compatible video (av01, compatible with iPhone 15 Pro
                          and newer) and <q>best</q> audio (mp4a), no max video height, with
                          fallback to avc1 and other formats if necessary.
                        </li>
                        <li>
                          <span className="settings-current">
                            {'bestvideo[format_id!*=-sr]+bestaudio/best[format_id!*=-sr]'}
                          </span>
                          : <q>best</q> video and <q>best</q> audio (yt-dlp's choice), no max
                          height, but excludes YouTube's AI-upscaled <q>Super Resolution</q>{' '}
                          formats. yt-dlp tags these with{' '}
                          <span className="settings-current">-sr</span> in the format ID, so this
                          filters them out without otherwise changing selection.
                        </li>
                        <li>
                          <span className="settings-current">
                            {
                              'bestvideo[format_id!*=-sr][height<=1080]+bestaudio/best[format_id!*=-sr][height<=1080]'
                            }
                          </span>
                          : same as the 1080p example above, but also excludes those AI-upscaled
                          formats.
                        </li>
                        <li>This can also be configured on a per channel basis.</li>
                        <li>
                          More details{' '}
                          <a
                            target="_blank"
                            href="https://github.com/yt-dlp/yt-dlp?tab=readme-ov-file#format-selection"
                          >
                            here
                          </a>
                          .
                        </li>
                      </ul>
                    </li>
                    <li>
                      Change the criteria what is considered <i>best</i> by yt-dlp. That is
                      equivalent to <i>--format-sort</i> argument. Examples:
                      <ul>
                        <li>
                          <span className="settings-current">res,codec:av1</span>: prefer AV1 over
                          all other video codecs.
                        </li>
                        <li>Not all codecs are supported by all browsers.</li>
                        <li>
                          More details{' '}
                          <a
                            target="_blank"
                            href="https://github.com/yt-dlp/yt-dlp?tab=readme-ov-file#sorting-formats"
                          >
                            here
                          </a>
                          .
                        </li>
                      </ul>
                    </li>
                    <li>
                      Extractor language will change how a video gets indexed. Index language
                      configuration
                      <ul>
                        <li>
                          That will only have an effect if the uploader provides translations.
                        </li>
                        <li>Add as two letter ISO language code.</li>
                        <li>
                          More details{' '}
                          <a target="_blank" href="https://github.com/yt-dlp/yt-dlp#youtube">
                            here
                          </a>
                          .
                        </li>
                      </ul>
                    </li>
                    <li>
                      Embedding metadata adds additional metadata and thumbnails directly to the mp4
                      file.
                    </li>
                  </ul>
                </div>
              )}
              <div className="settings-box-wrapper">
                <div>
                  <p>Select download format for yt-dlp.</p>
                </div>
                <InputConfig
                  type="text"
                  name="downloads.format"
                  value={downloadsFormat}
                  setValue={setDownloadsFormat}
                  oldValue={appSettingsConfig.downloads.format}
                  updateCallback={handleUpdateConfig}
                />
              </div>
              <div className="settings-box-wrapper">
                <div>
                  <p>Sort download formats</p>
                </div>
                <InputConfig
                  type="text"
                  name="downloads.format_sort"
                  value={downloadsFormatSort}
                  setValue={setDownloadsFormatSort}
                  oldValue={appSettingsConfig.downloads.format_sort}
                  updateCallback={handleUpdateConfig}
                />
              </div>
              <div className="settings-box-wrapper">
                <div>
                  <p>Extractor Language</p>
                </div>
                <InputConfig
                  type="text"
                  name="downloads.extractor_lang"
                  value={downloadsExtractorLang}
                  setValue={setDownloadsExtractorLang}
                  oldValue={appSettingsConfig.downloads.extractor_lang}
                  updateCallback={handleUpdateConfig}
                />
              </div>
              <div className="settings-box-wrapper">
                <div>
                  <p>Embed metadata</p>
                </div>
                <ToggleConfig
                  name="downloads.add_metadata"
                  value={embedMetadata}
                  updateCallback={handleUpdateConfig}
                />
              </div>
            </div>
            <div className="info-box-item">
              <h2 id="subtitles">Subtitles</h2>
              {userConfig.show_help_text && (
                <div className="help-text">
                  <p>Additional subtitle options show once you choose a language.</p>
                  <ul>
                    <li>
                      Choose which subtitles to download, add comma separated language codes, e.g.{' '}
                      <span className="settings-current">en, de, zh-Hans</span>
                    </li>
                    <li>
                      Enabling auto generated subtitles adds fallback to less accurate auto
                      generated subtitles from YT.
                    </li>
                    <li>
                      Indexing subtitles add the fulltext to the ES index. Not recommended on low
                      end hardware.
                    </li>
                  </ul>
                </div>
              )}
              <div className="settings-box-wrapper">
                <div>
                  <p>Choose subtitle language</p>
                </div>
                <InputConfig
                  type="text"
                  name="downloads.subtitle"
                  value={subtitleLang}
                  setValue={setSubtitleLang}
                  oldValue={appSettingsConfig?.downloads.subtitle}
                  updateCallback={handleUpdateConfig}
                />
              </div>
              {appSettingsConfig?.downloads.subtitle && (
                <>
                  <div className="settings-box-wrapper">
                    <div>
                      <p>Enable auto generated subtitles</p>
                    </div>
                    <div className="toggle">
                      <div className="toggleBox">
                        <input
                          name="subtitle_source"
                          type="checkbox"
                          checked={subtitleSource === 'auto'}
                          onChange={event => {
                            handleUpdateConfig(
                              'downloads.subtitle_source',
                              event.target.checked ? 'auto' : 'user',
                            );
                          }}
                        />
                        {subtitleSource === 'user' && (
                          <label htmlFor="" className="ofbtn">
                            Off
                          </label>
                        )}
                        {subtitleSource === 'auto' && (
                          <label htmlFor="" className="onbtn">
                            On
                          </label>
                        )}
                      </div>
                    </div>
                  </div>
                  <div className="settings-box-wrapper">
                    <div>
                      <p>Enable subtitle index</p>
                    </div>
                    <ToggleConfig
                      name="downloads.subtitle_index"
                      value={indexSubtitles}
                      updateCallback={handleUpdateConfig}
                    />
                  </div>
                </>
              )}
            </div>
            <div className="info-box-item">
              <h2 id="comments">Comments</h2>
              {userConfig.show_help_text && (
                <div className="help-text">
                  <p>Additional options show once you set a comment index option.</p>
                  <ul>
                    <li>
                      Download and index comments. Browsable on the video detail page. Example:
                      <ul>
                        <li>
                          <span className="settings-current">all,100,all,30,all</span>: Get 100
                          max-parents and 30 max-replies-per-thread at any depth.
                        </li>
                        <li>
                          <span className="settings-current">1000,all,all,50,2</span>: Get a total
                          of 1000 comments over all, 50 replies per thread, only 2 levels of depth.
                        </li>
                        <li>
                          Values are in the format:{' '}
                          <span className="settings-current">
                            max-comments,max-parents,max-replies,max-replies-per-thread,max-depth
                          </span>
                          .
                        </li>
                        <li>Choose wisely, as extracting comments is slow.</li>
                      </ul>
                    </li>
                    <li>The sort order changes how comments are indexed.</li>
                  </ul>
                </div>
              )}
              <div className="settings-box-wrapper">
                <div>
                  <p>Index comments</p>
                </div>
                <InputConfig
                  type="text"
                  name="downloads.comment_max"
                  value={commentsMax}
                  setValue={setCommentsMax}
                  oldValue={appSettingsConfig?.downloads.comment_max}
                  updateCallback={handleUpdateConfig}
                />
              </div>
              {appSettingsConfig?.downloads.comment_max && (
                <div className="settings-box-wrapper">
                  <div>
                    <p>Comment sort method</p>
                  </div>
                  <div>
                    <select
                      name="downloads.comment_sort"
                      value={commentsSort}
                      onChange={event => {
                        handleUpdateConfig('downloads.comment_sort', event.target.value);
                      }}
                    >
                      <option value="top">sort comments by top</option>
                      <option value="new">sort comments by new</option>
                    </select>
                  </div>
                </div>
              )}
            </div>
            <div className="info-box-item">
              <h2 id="cookie">Cookie</h2>
              {userConfig.show_help_text && (
                <div className="help-text">
                  <p>
                    Importing your cookie will authenticate requests to YT with your user account.
                  </p>
                  <ul>
                    <li>Adding your cookie can avoid your requests getting blocked.</li>
                    <li>This expects your cookie in Netscape format.</li>
                    <li>
                      For automatic cookie import use Tube Archivist Companion{' '}
                      <a href="https://github.com/tubearchivist/browser-extension" target="_blank">
                        browser extension
                      </a>
                      .
                    </li>
                    <li>
                      The PO Token Provider URL running external to tubearchivist. Make sure to
                      review{' '}
                      <a
                        target="_blank"
                        href="https://docs.tubearchivist.com/settings/application/#po-token-provider-url"
                      >
                        User Guide
                      </a>
                    </li>
                  </ul>
                </div>
              )}
              <div className="settings-box-wrapper">
                <div>
                  <p>Use your cookie for yt-dlp</p>
                </div>
                <div>
                  {response?.cookieState?.cookie_enabled ? (
                    <>
                      <p>
                        Cookie enabled. Last validation:{' '}
                        <span className="settings-current">
                          {response.cookieState.validated_str}
                        </span>
                        .
                      </p>
                      <div className="button-box">
                        <button className="danger-button" onClick={handleCookieRevoke}>
                          Revoke
                        </button>
                        <button onClick={handleCookieValidate}>Validate</button>
                      </div>
                    </>
                  ) : (
                    <p>Cookie disabled</p>
                  )}
                  {showCookieForm ? (
                    <>
                      <textarea
                        rows={4}
                        value={cookieFormData}
                        onChange={e => {
                          setCookieFormData(e.currentTarget.value);
                        }}
                      />
                      <div className="button-box">
                        <button onClick={handleCookieUpdate} type="submit">
                          Submit
                        </button>
                        <button onClick={() => setShowCookieForm(false)}>Cancel</button>
                      </div>
                    </>
                  ) : (
                    <div>
                      <button onClick={() => setShowCookieForm(true)}>Update Cookie</button>
                    </div>
                  )}
                </div>
              </div>
              <div className="settings-box-wrapper">
                <div>
                  <p>PO Token Provider URL</p>
                </div>
                <InputConfig
                  type="text"
                  name="downloads.pot_provider_url"
                  value={potProviderUrl}
                  setValue={setPotProviderUrl}
                  oldValue={appSettingsConfig.downloads.pot_provider_url}
                  updateCallback={handleUpdateConfig}
                />
              </div>
            </div>
            <div className="info-box-item">
              <h2 id="sntegrations">Integrations</h2>
              {userConfig.show_help_text && (
                <div className="help-text">
                  <ul>
                    <li>The API token is used to make automater requests to TA through the API.</li>
                    <li>
                      Return Youtube Dislike is a crowdsourced database of dislikes.
                      <ul>
                        <li>Make sure to contribute to this excellent project.</li>
                        <li>
                          More details{' '}
                          <a
                            href="https://returnyoutubedislike.com/"
                            target="_blank"
                            rel="noopener noreferrer"
                          >
                            here
                          </a>
                          .
                        </li>
                      </ul>
                    </li>
                    <li>
                      Sponsorblock is a crowdsourced database of timestamps marking sponsored slots
                      for a video.
                      <ul>
                        <li>This can also be configured on a per channel basis.</li>
                        <li>Make sure to contribute to this excellent project.</li>
                        <li>
                          More details{' '}
                          <a
                            href="https://sponsor.ajay.app/"
                            target="_blank"
                            rel="noopener noreferrer"
                          >
                            here
                          </a>
                          .
                        </li>
                      </ul>
                    </li>
                  </ul>
                </div>
              )}
              <div className="settings-box-wrapper">
                <div>
                  <p>API token</p>
                </div>
                <div>
                  {showApiToken && <input readOnly value={apiToken} />}
                  <button onClick={() => setShowApiToken(!showApiToken)}>
                    {showApiToken ? 'Hide' : 'Show'}
                  </button>
                  {showApiToken && (
                    <Button
                      className="danger-button"
                      label="Revoke"
                      type="button"
                      onClick={async () => {
                        await deleteApiToken();
                        setShowApiToken(false);
                        setRefresh(true);
                      }}
                    />
                  )}
                </div>
              </div>
              <div className="settings-box-wrapper">
                <div>
                  <p>
                    Enable{' '}
                    <a
                      href="https://returnyoutubedislike.com/"
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      returnyoutubedislike
                    </a>
                  </p>
                </div>
                <ToggleConfig
                  name="downloads.integrate_ryd"
                  value={downloadDislikes}
                  updateCallback={handleUpdateConfig}
                />
              </div>
              <div className="settings-box-wrapper">
                <div>
                  <p>
                    Enable{' '}
                    <a href="https://sponsor.ajay.app/" target="_blank" rel="noopener noreferrer">
                      Sponsorblock
                    </a>
                  </p>
                </div>
                <ToggleConfig
                  name="downloads.integrate_sponsorblock"
                  value={enableSponsorBlock}
                  updateCallback={handleUpdateConfig}
                />
              </div>
              <div className="settings-box-wrapper">
                <div>
                  <p>Enable Cast</p>
                </div>
                <ToggleConfig
                  name="application.enable_cast"
                  value={enableCast}
                  updateCallback={handleUpdateConfig}
                />
              </div>
            </div>
            <div className="info-box-item">
              <h2 id="downscale">Downscale</h2>
              {userConfig.show_help_text && (
                <div className="help-text">
                  <ul>
                    <li>
                      Max concurrent downscale jobs limits how many downscale encodes run at the
                      same time.
                      <ul>
                        <li>Leave empty for no additional limit.</li>
                        <li>
                          Still bounded by the Celery worker's overall concurrency, and shares
                          worker slots with downloads and other background tasks.
                        </li>
                      </ul>
                    </li>
                    <li>
                      Downscale encoder, quality (CRF) and speed preset apply to all future
                      downscale jobs.
                      <ul>
                        <li>H.264 is the most compatible, AV1 compresses best but is slowest.</li>
                        <li>Lower CRF means higher quality and larger files.</li>
                      </ul>
                    </li>
                    <li>
                      Hardware (VAAPI) options offload encoding to an Intel iGPU.
                      <ul>
                        <li>
                          Requires the GPU passed through to the container (<code>/dev/dri</code>)
                          and a working VAAPI driver.
                        </li>
                        <li>
                          If a hardware job fails (missing device, driver issue, or this codec
                          isn&apos;t supported on your GPU), it fails with the ffmpeg error shown.
                          There is no automatic fallback to software encoding.
                        </li>
                        <li>
                          AV1 hardware encode needs a fairly recent GPU (Intel Arc, Meteor Lake or
                          newer) &mdash; most current-generation Intel iGPUs (e.g. UHD 7xx/Xe-LP)
                          only support AV1 hardware decode, not encode.
                        </li>
                      </ul>
                    </li>
                  </ul>
                </div>
              )}
              <div className="settings-box-wrapper">
                <div>
                  <p>Max concurrent downscale jobs</p>
                </div>
                <InputConfig
                  type="number"
                  name="application.downscale_max_concurrent"
                  value={downscaleMaxConcurrent}
                  setValue={setDownscaleMaxConcurrent}
                  oldValue={appSettingsConfig?.application.downscale_max_concurrent ?? null}
                  updateCallback={handleUpdateConfig}
                />
              </div>
              <div className="settings-box-wrapper">
                <div>
                  <p>Downscale encoder</p>
                </div>
                <div>
                  <select
                    name="application.downscale_encoder"
                    value={downscaleEncoder}
                    onChange={event => {
                      setDownscaleEncoder(event.target.value);
                      handleUpdateConfig('application.downscale_encoder', event.target.value);
                    }}
                  >
                    {ENCODER_OPTIONS.map(option => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
              <div className="settings-box-wrapper">
                <div>
                  <p>Downscale quality ({QUALITY_LABELS[downscaleEncoder] ?? 'CRF'})</p>
                </div>
                <div>
                  <InputConfig
                    type="number"
                    name="application.downscale_crf"
                    value={downscaleCrf}
                    setValue={setDownscaleCrf}
                    oldValue={appSettingsConfig?.application.downscale_crf ?? null}
                    updateCallback={handleUpdateConfig}
                  />
                  <ul className="settings-current">
                    {downscaleEncoder === 'h264' && (
                      <li>H.264: 18-22 near-lossless, 23 balanced (default), 26-28 smaller files.</li>
                    )}
                    {downscaleEncoder === 'h265' && (
                      <li>H.265: 24-26 near-lossless, 28 balanced (default), 30-32 smaller files.</li>
                    )}
                    {downscaleEncoder === 'av1' && (
                      <li>
                        AV1: 24-28 near-lossless, 30-35 balanced (default), 36-40 smaller files.
                      </li>
                    )}
                    {downscaleEncoder === 'h264_vaapi' && (
                      <li>
                        H.264 (Hardware): QP 18-22 near-lossless, 23-26 balanced, 28-32 smaller
                        files.
                      </li>
                    )}
                    {downscaleEncoder === 'h265_vaapi' && (
                      <li>
                        H.265 (Hardware): QP 20-24 near-lossless, 25-28 balanced, 30-34 smaller
                        files.
                      </li>
                    )}
                    {downscaleEncoder === 'av1_vaapi' && (
                      <li>
                        AV1 (Hardware): applied as an ICQ quality target rather than a raw QP
                        (av1_vaapi doesn&apos;t support QP/CQP in ffmpeg) &mdash; range depends on
                        your driver; only usable on GPUs with AV1 hardware encode support.
                      </li>
                    )}
                    {isHardwareEncoder && (
                      <li>
                        Hardware QP and software CRF are different scales &mdash; a value tuned for
                        one is not directly portable to the other. Lower the number when switching
                        from software to hardware to target similar visual quality.
                      </li>
                    )}
                  </ul>
                </div>
              </div>
              <div className="settings-box-wrapper">
                <div>
                  <p>Downscale speed (preset)</p>
                </div>
                <div>
                  {presetUnsupported ? (
                    <p className="settings-current">
                      Not applicable &mdash; H.265/AV1 hardware encoders have no speed preset in
                      ffmpeg, so there is nothing to set here while one of them is selected.
                    </p>
                  ) : (
                    <>
                      <select
                        name="application.downscale_preset"
                        value={downscalePreset}
                        onChange={event => {
                          setDownscalePreset(event.target.value);
                          handleUpdateConfig('application.downscale_preset', event.target.value);
                        }}
                      >
                        {PRESET_OPTIONS.map(preset => (
                          <option key={preset} value={preset}>
                            {preset}
                          </option>
                        ))}
                      </select>
                      <ul className="settings-current">
                        <li>
                          Trades encode speed against compression efficiency at the same CRF/QP
                          &mdash; slower presets shrink the file more for the same quality, faster
                          presets encode quicker but produce larger files.
                        </li>
                        {codecFamily === 'av1' && !isHardwareEncoder && (
                          <li>
                            AV1 (libsvtav1) uses its own numeric 0-13 speed scale internally &mdash;
                            the named preset chosen here is mapped onto it.
                          </li>
                        )}
                        {downscaleEncoder === 'h264_vaapi' && (
                          <li>
                            H.264 (Hardware) maps this onto Intel&apos;s Quick Sync &quot;Target
                            Usage&quot; (roughly 1-7, best-to-fastest quality) via ffmpeg&apos;s
                            <code>-quality</code> option &mdash; a much narrower range than the
                            software presets, so several named presets in a row can behave
                            identically on hardware.
                          </li>
                        )}
                      </ul>
                      {presetTableRows && (
                        <>
                          <p className="settings-current">
                            Approximate, relative to that encoder&apos;s own &quot;medium&quot;
                            preset &mdash; ballpark figures from typical community benchmarks, not
                            measured on this device. Actual results depend heavily on source
                            content, resolution and hardware.
                            {downscaleEncoder === 'h264_vaapi' && (
                              <>
                                {' '}
                                Quick Sync isn&apos;t directly comparable to software x264 presets
                                either &mdash; even its best quality setting generally lands closer
                                to x264 &quot;fast&quot;-&quot;medium&quot; quality, just
                                dramatically faster since it runs on dedicated silicon rather than
                                the CPU.
                              </>
                            )}
                          </p>
                          <table className="preset-reference-table">
                            <thead>
                              <tr>
                                <th>Preset</th>
                                <th>Encode time</th>
                                <th>File size</th>
                              </tr>
                            </thead>
                            <tbody>
                              {presetTableRows.map(row => (
                                <tr
                                  key={row.preset}
                                  className={row.preset === downscalePreset ? 'active-row' : ''}
                                >
                                  <td>{row.preset}</td>
                                  <td>{row.time}</td>
                                  <td>{row.size}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </>
                      )}
                    </>
                  )}
                </div>
              </div>
              <div className="settings-box-wrapper">
                <div>
                  <p>Test hardware encoders</p>
                </div>
                <div>
                  {isTestingEncoders ? (
                    <LoadingIndicator />
                  ) : (
                    <Button label="Run test" onClick={handleTestEncoders} />
                  )}
                  {encoderTestResults.length > 0 && (
                    <ul className="settings-current">
                      {encoderTestResults.map(result => (
                        <li key={result.encoder}>
                          {ENCODER_LABELS[result.encoder] ?? result.encoder}:{' '}
                          {result.ok ? 'works' : `failed - ${result.message}`}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>
            </div>
            <div className="info-box-item">
              <MembershipAppsettings show_help_text={userConfig.show_help_text} />
            </div>
            <div className="info-box-item">
              <h2>Snapshots</h2>
              {userConfig.show_help_text && (
                <div className="help-text">
                  <p>
                    Automatically create daily deduplicated snapshots of the index, stored in
                    Elasticsearch. Restoring from snapshot replaced your current index with the
                    index from the snapshot.
                  </p>
                </div>
              )}
              <div className="settings-box-wrapper">
                <div>
                  <p>Enable Index Snapshot</p>
                </div>
                <ToggleConfig
                  name="application.enable_snapshot"
                  value={enableSnapshots}
                  updateCallback={handleUpdateConfig}
                />
              </div>
              <div className="settings-box-wrapper">
                <div></div>
                <div>
                  <div>
                    {appSettingsConfig?.application.enable_snapshot && snapshots && (
                      <>
                        <p>
                          Create next snapshot:{' '}
                          <span className="settings-current">{snapshots.next_exec_str}</span>,
                          snapshots expire after{' '}
                          <span className="settings-current">{snapshots.expire_after}</span>
                          . <br />
                          {isSnapshotQueued && <span>Snapshot in progress</span>}
                          {!isSnapshotQueued && (
                            <Button
                              label="Create snapshot now"
                              id="createButton"
                              onClick={async () => {
                                setIsSnapshotQueued(true);
                                await queueSnapshot();
                              }}
                            />
                          )}
                        </p>
                        <br />
                        {restoringSnapshot && <p>Snapshot restore started</p>}
                        {!restoringSnapshot && snapshots.snapshots && (
                          <>
                            {snapshots.snapshots?.slice(0, visibleSnapshotCount).map(snapshot => (
                              <p key={snapshot.id}>
                                <Button
                                  label="Restore"
                                  onClick={async () => {
                                    setRestoringSnapshot(true);
                                    await restoreSnapshot(snapshot.id);
                                  }}
                                />{' '}
                                Snapshot created on:{' '}
                                <span className="settings-current">{snapshot.start_date}</span>,
                                took{' '}
                                <span className="settings-current">{snapshot.duration_s}s</span> to
                                create. State: <i>{snapshot.state}</i>
                              </p>
                            ))}
                            {visibleSnapshotCount < snapshots.snapshots.length && (
                              <Button
                                label="Load More"
                                onClick={() => {
                                  setVisibleSnapshotCount(visibleSnapshotCount + 10);
                                }}
                              />
                            )}
                          </>
                        )}
                      </>
                    )}
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      <PaginationDummy />
    </>
  );
};

export default SettingsApplication;
