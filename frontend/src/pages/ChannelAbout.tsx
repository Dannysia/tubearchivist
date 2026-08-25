import { useNavigate, useOutletContext, useParams } from 'react-router-dom';
import ChannelOverview from '../components/ChannelOverview';
import { useEffect, useState } from 'react';
import loadChannelById, { ChannelResponseType } from '../api/loader/loadChannelById';
import Linkify from '../components/Linkify';
import deleteChannel from '../api/actions/deleteChannel';
import Routes from '../configuration/routes/RouteList';
import queueReindex, { ReindexType, ReindexTypeEnum } from '../api/actions/queueReindex';
import formatDate from '../functions/formatDates';
import PaginationDummy from '../components/PaginationDummy';
import Button from '../components/Button';
import updateChannelOverwrites from '../api/actions/updateChannelOverwrite';
import useIsAdmin from '../functions/useIsAdmin';
import InputConfig from '../components/InputConfig';
import ToggleConfig from '../components/ToggleConfig';
import { useUserConfigStore } from '../stores/UserConfigStore';
import { ApiResponseType } from '../functions/APIClient';
import startChannelDownscale, {
  ChannelDownscaleResponseType,
} from '../api/actions/startChannelDownscale';
import loadChannelAggs, { ChannelAggsType } from '../api/loader/loadChannelAggs';
import ChannelStats from '../components/ChannelStats';
import { FileSizeUnits } from '../api/actions/updateUserConfig';

const DOWNSCALE_LADDER = [2160, 1440, 1080, 720, 480, 360, 240];

export type ChannelBaseOutletContextType = {
  currentPage: number;
  setCurrentPage: (page: number) => void;
  startNotification: boolean;
  setStartNotification: (status: boolean) => void;
};

export type OutletContextType = {
  currentPage: number;
  setCurrentPage: (page: number) => void;
};

type ChannelAboutParams = {
  channelId: string;
};

const ChannelAbout = () => {
  const { channelId } = useParams() as ChannelAboutParams;
  const { userConfig } = useUserConfigStore();
  const { setStartNotification } = useOutletContext() as ChannelBaseOutletContextType;
  const navigate = useNavigate();
  const isAdmin = useIsAdmin();

  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [descriptionExpanded, setDescriptionExpanded] = useState(false);
  const [reindex, setReindex] = useState(false);
  const [refresh, setRefresh] = useState(true);
  const [showDownscaleForm, setShowDownscaleForm] = useState(false);
  const [downscaleTargetHeight, setDownscaleTargetHeight] = useState(DOWNSCALE_LADDER[0]);
  const [downscaleResult, setDownscaleResult] = useState<ChannelDownscaleResponseType | null>(null);

  const [channelResponse, setChannelResponse] = useState<ApiResponseType<ChannelResponseType>>();
  const [channelAggsResponse, setChannelAggsResponse] =
    useState<ApiResponseType<ChannelAggsType>>();

  const [downloadFormat, setDownloadFormat] = useState<string | null>(null);
  const [autoDeleteAfter, setAutoDeleteAfter] = useState<number | null>(null);
  const [indexPlaylists, setIndexPlaylists] = useState(false);
  const [enableSponsorblock, setEnableSponsorblock] = useState<boolean | null>(null);
  const [pageSizeVideo, setPageSizeVideo] = useState<number | null>(null);
  const [pageSizeShorts, setPageSizeShorts] = useState<number | null>(null);
  const [pageSizeStreams, setPageSizeStreams] = useState<number | null>(null);

  const { data: channelResponseData } = channelResponse ?? {};
  const { data: channelAggs } = channelAggsResponse ?? {};

  const channel = channelResponseData;
  const useSiUnits = userConfig.file_size_unit === FileSizeUnits.Metric;

  useEffect(() => {
    (async () => {
      if (refresh) {
        const [channelResponse, channelAggsResponse] = await Promise.all([
          loadChannelById(channelId),
          loadChannelAggs(channelId),
        ]);
        const { data: channelResponseData } = channelResponse;

        setChannelResponse(channelResponse);
        setChannelAggsResponse(channelAggsResponse);
        setDownloadFormat(channelResponseData?.channel_overwrites?.download_format ?? null);
        setAutoDeleteAfter(channelResponseData?.channel_overwrites?.autodelete_days ?? null);
        setIndexPlaylists(channelResponseData?.channel_overwrites?.index_playlists ?? false);
        setEnableSponsorblock(
          channelResponseData?.channel_overwrites?.integrate_sponsorblock ?? null,
        );
        setPageSizeVideo(
          channelResponseData?.channel_overwrites?.subscriptions_channel_size ?? null,
        );
        setPageSizeShorts(
          channelResponseData?.channel_overwrites?.subscriptions_shorts_channel_size ?? null,
        );
        setPageSizeStreams(
          channelResponseData?.channel_overwrites?.subscriptions_live_channel_size ?? null,
        );

        setRefresh(false);
      }
    })();
  }, [refresh, channelId]);

  const handleUpdateConfig = async (
    configKey: string,
    configValue: string | boolean | number | null,
  ) => {
    if (!channel) return;
    await updateChannelOverwrites(channel.channel_id, configKey, configValue);
    setRefresh(true);
  };

  const handleToggleSponsorBlock = async (isEnabled: boolean) => {
    if (isEnabled) {
      setEnableSponsorblock(true);
      await handleUpdateConfig('integrate_sponsorblock', false);
    } else {
      await handleUpdateConfig('integrate_sponsorblock', null);
      setEnableSponsorblock(null);
    }
  };

  if (!channel) {
    return 'Channel not found!';
  }

  return (
    <>
      <title>{`TA | Channel: About ${channel.channel_name}`}</title>
      <div className="boxed-content">
        <div className="info-box info-box-3">
          <ChannelOverview
            channelId={channel.channel_id}
            channelname={channel.channel_name}
            channelSubs={channel.channel_subs}
            channelSubscribed={channel.channel_subscribed}
            channelThumbUrl={channel.channel_thumb_url}
            setRefresh={setRefresh}
          />

          <div className="info-box-item">
            <div>
              <p>Last refreshed: {formatDate(channel.channel_last_refresh)}</p>
              {channel.channel_subscribed && channel.channel_subscribed_next_check && (
                <p>Next scan: {formatDate(channel.channel_subscribed_next_check, true)}</p>
              )}
              {channel.channel_active && (
                <p>
                  Youtube:{' '}
                  <a
                    href={`https://www.youtube.com/channel/${channel.channel_id}`}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Active
                  </a>
                </p>
              )}
              {!channel.channel_active && <p>Youtube: Deactivated</p>}
            </div>
          </div>

          <div className="info-box-item">
            <div>
              {isAdmin && (
                <>
                  <div className="button-box">
                    {!showDeleteConfirm && (
                      <Button
                        label="Delete Channel"
                        id="delete-item"
                        onClick={() => setShowDeleteConfirm(!showDeleteConfirm)}
                      />
                    )}

                    {showDeleteConfirm && (
                      <div className="delete-confirm">
                        <span>Delete {channel.channel_name} including all videos? </span>

                        <Button
                          label="Delete"
                          className="danger-button"
                          onClick={async () => {
                            await deleteChannel(channelId);
                            navigate(Routes.Channels);
                          }}
                        />

                        <Button
                          label="Cancel"
                          onClick={() => setShowDeleteConfirm(!showDeleteConfirm)}
                        />
                      </div>
                    )}
                  </div>
                  <br></br>
                  {reindex && <p>Reindex scheduled</p>}
                  {!reindex && (
                    <div id="reindex-button" className="button-box">
                      <Button
                        label="Reindex"
                        title={`Reindex Channel ${channel.channel_name}`}
                        onClick={async () => {
                          await queueReindex([channelId], ReindexTypeEnum.channel as ReindexType);

                          setReindex(true);
                          setStartNotification(true);
                        }}
                      />{' '}
                      <Button
                        label="Reindex Videos"
                        title={`Reindex Videos of ${channel.channel_name}`}
                        onClick={async () => {
                          await queueReindex(
                            [channelId],
                            ReindexTypeEnum.channel as ReindexType,
                            true,
                          );

                          setReindex(true);
                          setStartNotification(true);
                        }}
                      />
                    </div>
                  )}
                  <br></br>
                  <div id="batch-downscale-button" className="button-box">
                    {!showDownscaleForm && !downscaleResult && (
                      <Button
                        label="Batch Downscale"
                        title={`Downscale all videos of ${channel.channel_name}`}
                        onClick={() => setShowDownscaleForm(true)}
                      />
                    )}

                    {showDownscaleForm && (
                      <div className="delete-confirm">
                        <span>Downscale all videos above: </span>
                        <select
                          value={downscaleTargetHeight}
                          onChange={event =>
                            setDownscaleTargetHeight(Number(event.currentTarget.value))
                          }
                        >
                          {DOWNSCALE_LADDER.map(height => (
                            <option key={height} value={height}>
                              {height}p
                            </option>
                          ))}
                        </select>
                        <Button
                          label="Start"
                          onClick={async () => {
                            const response = await startChannelDownscale(
                              channelId,
                              downscaleTargetHeight,
                            );
                            setDownscaleResult(response.data ?? { queued: [], skipped: [] });
                            setShowDownscaleForm(false);
                            setTimeout(() => setDownscaleResult(null), 6000);
                          }}
                        />
                        <Button label="Cancel" onClick={() => setShowDownscaleForm(false)} />
                      </div>
                    )}

                    {downscaleResult && (
                      <p>
                        Queued {downscaleResult.queued.length} video(s) for downscale.
                        {downscaleResult.skipped.length > 0 && (
                          <> {downscaleResult.skipped.length} already in progress, skipped.</>
                        )}{' '}
                        <Button
                          label="View Downscale Queue"
                          onClick={() => navigate(Routes.Downscale)}
                        />
                      </p>
                    )}
                  </div>
                </>
              )}
            </div>
          </div>
        </div>

        <div className="info-box info-box-3">
          <ChannelStats channelAggs={channelAggs} useSIUnits={useSiUnits} />
        </div>

        {channel.channel_description && (
          <div className="description-box">
            <p
              id={descriptionExpanded ? 'text-expand-expanded' : 'text-expand'}
              className="description-text"
            >
              <Linkify>{channel.channel_description}</Linkify>
            </p>

            <Button
              label="Show more"
              id="text-expand-button"
              onClick={() => setDescriptionExpanded(!descriptionExpanded)}
            />
          </div>
        )}

        {channel?.channel_tags && channel.channel_tags.length > 0 && (
          <div className="description-box">
            <div className="video-tag-box">
              {channel.channel_tags.map(tag => {
                return (
                  <span key={tag} className="video-tag">
                    {tag}
                  </span>
                );
              })}
            </div>
          </div>
        )}

        {isAdmin && (
          <div className="info-box">
            <div className="info-box-item">
              <h2>Channel Customization</h2>
              {userConfig.show_help_text && (
                <div className="help-text">
                  <ul>
                    <li>Overwrite the download format over the format set globally.</li>
                    <li>Autodelete watched after x days overwrites the global setting.</li>
                    <li>
                      Indexing playlists indexes all playlists from that channel.
                      <ul>
                        <li>
                          Only activate that for channels you care about the playlists. This is
                          slow.
                        </li>
                        <li>
                          More details{' '}
                          <a target="_blank" href="https://docs.tubearchivist.com/channels/#about">
                            here
                          </a>
                          .
                        </li>
                      </ul>
                    </li>
                    <li>
                      Once you click on <i>Configure</i>, this will activate sponsorblock settings.
                    </li>
                  </ul>
                </div>
              )}
              <div className="settings-box-wrapper">
                <div>
                  <p>Download Format</p>
                </div>
                <InputConfig
                  type="text"
                  name="download_format"
                  value={downloadFormat}
                  setValue={setDownloadFormat}
                  oldValue={channel.channel_overwrites?.download_format ?? null}
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
                  name="autodelete_days"
                  value={autoDeleteAfter}
                  setValue={setAutoDeleteAfter}
                  oldValue={channel.channel_overwrites?.autodelete_days ?? null}
                  updateCallback={handleUpdateConfig}
                />
              </div>
              <div className="settings-box-wrapper">
                <div>
                  <p>Index playlists</p>
                </div>
                <ToggleConfig
                  name="index_playlists"
                  value={indexPlaylists}
                  updateCallback={handleUpdateConfig}
                />
              </div>
              <div className="settings-box-wrapper">
                <div>
                  <p>
                    Overwrite{' '}
                    <a href="https://sponsor.ajay.app/" target="_blank" rel="noopener noreferrer">
                      SponsorBlock
                    </a>
                  </p>
                </div>
                <div>
                  {enableSponsorblock !== null ? (
                    <ToggleConfig
                      name="integrate_sponsorblock"
                      value={enableSponsorblock}
                      updateCallback={handleUpdateConfig}
                      resetCallback={handleToggleSponsorBlock}
                    />
                  ) : (
                    <button onClick={() => handleToggleSponsorBlock(true)}>Configure</button>
                  )}
                </div>
              </div>
            </div>
            <div className="info-box-item">
              <h2>Page Size Overrides</h2>
              {userConfig.show_help_text && (
                <div className="help-text">
                  <p>
                    Disable standard videos, shorts, or streams for this channel by setting their
                    page size to 0 (zero).
                  </p>
                </div>
              )}
              <div className="settings-box-wrapper">
                <div>
                  <p>Videos page size</p>
                </div>
                <InputConfig
                  type="number"
                  name="subscriptions_channel_size"
                  value={pageSizeVideo}
                  setValue={setPageSizeVideo}
                  oldValue={channel.channel_overwrites?.subscriptions_channel_size ?? null}
                  updateCallback={handleUpdateConfig}
                />
              </div>
              <div className="settings-box-wrapper">
                <div>
                  <p>Shorts page size</p>
                </div>
                <InputConfig
                  type="number"
                  name="subscriptions_shorts_channel_size"
                  value={pageSizeShorts}
                  setValue={setPageSizeShorts}
                  oldValue={channel.channel_overwrites?.subscriptions_shorts_channel_size ?? null}
                  updateCallback={handleUpdateConfig}
                />
              </div>
              <div className="settings-box-wrapper">
                <div>
                  <p>Live streams page size</p>
                </div>
                <InputConfig
                  type="number"
                  name="subscriptions_live_channel_size"
                  value={pageSizeStreams}
                  setValue={setPageSizeStreams}
                  oldValue={channel.channel_overwrites?.subscriptions_live_channel_size ?? null}
                  updateCallback={handleUpdateConfig}
                />
              </div>
            </div>
          </div>
        )}
      </div>

      <PaginationDummy />
    </>
  );
};

export default ChannelAbout;
