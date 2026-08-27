import { useEffect, useState } from 'react';
import Button from './Button';
import createImportMetadata, { ImportMetadataType } from '../api/actions/createImportMetadata';
import { ImportFileType } from '../api/loader/loadImportFiles';
import searchChannels from '../api/loader/searchChannels';
import { ChannelType } from '../pages/Channels';

type ImportMetadataModalProps = {
  // media files staged without metadata, offered as video id options so
  // the id does not have to be retyped from the file name
  candidates: ImportFileType[];
  onClose: () => void;
  onCreated: () => void;
};

type ChannelMode = 'existing' | 'new';

type FormState = {
  video_id: string;
  channel_id: string;
  channel_name: string;
  title: string;
  upload_date: string;
  description: string;
  thumbnail: string;
  view_count: string;
  like_count: string;
};

const EMPTY_FORM: FormState = {
  video_id: '',
  channel_id: '',
  channel_name: '',
  title: '',
  upload_date: '',
  description: '',
  thumbnail: '',
  view_count: '',
  like_count: '',
};

const errorMessage = (err: unknown): string => {
  if (err instanceof Error) return err.message;
  if (typeof err === 'object' && err !== null && 'message' in err) {
    return String((err as { message: unknown }).message);
  }

  return String(err);
};

const ImportMetadataModal = ({ candidates, onClose, onCreated }: ImportMetadataModalProps) => {
  const [form, setForm] = useState<FormState>({
    ...EMPTY_FORM,
    video_id: candidates[0]?.video_id ?? '',
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  // picking an indexed channel is the common case and avoids retyping a
  // 24 character id; a new one is only needed for a channel the archive
  // has never seen
  const [channelMode, setChannelMode] = useState<ChannelMode>('existing');
  const [channelSearch, setChannelSearch] = useState('');
  const [channelResults, setChannelResults] = useState<ChannelType[]>([]);
  const [searching, setSearching] = useState(false);

  useEffect(() => {
    const onEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };

    window.addEventListener('keydown', onEscape);

    return () => window.removeEventListener('keydown', onEscape);
  }, [onClose]);

  useEffect(() => {
    if (channelMode !== 'existing') return;

    // everything happens in the timer, including clearing: a state
    // update in the effect body itself renders twice per keystroke
    const timer = setTimeout(async () => {
      const term = channelSearch.trim();
      if (!term) {
        setChannelResults([]);
        return;
      }

      setSearching(true);
      const response = await searchChannels(term);
      setChannelResults(response.data?.results.channel_results ?? []);
      setSearching(false);
    }, 400);

    return () => clearTimeout(timer);
  }, [channelSearch, channelMode]);

  const selectChannel = (channel: ChannelType) => {
    setForm(current => ({
      ...current,
      channel_id: channel.channel_id,
      channel_name: channel.channel_name,
    }));
    setChannelSearch('');
    setChannelResults([]);
  };

  const switchChannelMode = (mode: ChannelMode) => {
    setChannelMode(mode);
    // whatever was picked or typed belongs to the other mode
    setForm(current => ({ ...current, channel_id: '', channel_name: '' }));
    setChannelSearch('');
    setChannelResults([]);
  };

  const setField = (field: keyof FormState, value: string) => {
    setForm(current => ({ ...current, [field]: value }));
  };

  // the backend validates all of this too, this only stops an obviously
  // incomplete form costing a round trip
  const isComplete =
    form.video_id.length === 11 &&
    !!form.channel_id &&
    !!form.channel_name &&
    !!form.title &&
    !!form.upload_date;

  const handleSubmit = async () => {
    setSaving(true);
    setError('');

    const metadata: ImportMetadataType = {
      video_id: form.video_id.trim(),
      channel_id: form.channel_id.trim(),
      channel_name: form.channel_name.trim(),
      title: form.title.trim(),
      upload_date: form.upload_date,
    };

    if (form.description) metadata.description = form.description;
    if (form.thumbnail) metadata.thumbnail = form.thumbnail.trim();
    if (form.view_count) metadata.view_count = Number(form.view_count);
    if (form.like_count) metadata.like_count = Number(form.like_count);

    try {
      const response = await createImportMetadata(metadata);
      if (response.error) {
        setError(response.error.error);
        setSaving(false);
        return;
      }
    } catch (err) {
      setError(errorMessage(err));
      setSaving(false);
      return;
    }

    setSaving(false);
    onCreated();
    onClose();
  };

  return (
    <div
      className="import-modal-backdrop"
      onClick={event => {
        // only a click on the backdrop itself, not one that bubbled up
        // out of the form
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="import-modal" role="dialog" aria-modal="true">
        <h2>Generate metadata file</h2>
        <p>
          <i>
            Writes <span className="settings-current">&lt;video id&gt;.info.json</span> into the
            import folder, next to the media file it belongs to. Use this when the video is no
            longer on YouTube, so there is nothing to look the metadata up from.
          </i>
        </p>
        <p>
          <i>
            These values are a fallback. The import still asks YouTube first, and only falls back to
            this file when YouTube returns nothing for the video.
          </i>
        </p>

        <div className="import-modal-form">
          <label>
            Video ID*
            {candidates.length > 0 && (
              <select
                value={form.video_id}
                onChange={event => setField('video_id', event.target.value)}
              >
                <option value="">-- staged media without metadata --</option>
                {candidates.map(file => (
                  <option key={file.filename} value={file.video_id ?? ''}>
                    {file.filename}
                  </option>
                ))}
              </select>
            )}
            <input
              type="text"
              value={form.video_id}
              maxLength={11}
              placeholder="hc5gku8LRTQ"
              onChange={event => setField('video_id', event.target.value)}
            />
          </label>

          <label>
            Title*
            <input
              type="text"
              value={form.title}
              onChange={event => setField('title', event.target.value)}
            />
          </label>

          <div className="import-modal-channel">
            <div className="import-modal-modes">
              <span>Channel*</span>
              <label>
                <input
                  type="radio"
                  name="channel_mode"
                  checked={channelMode === 'existing'}
                  onChange={() => switchChannelMode('existing')}
                />{' '}
                Select existing
              </label>
              <label>
                <input
                  type="radio"
                  name="channel_mode"
                  checked={channelMode === 'new'}
                  onChange={() => switchChannelMode('new')}
                />{' '}
                Add new
              </label>
            </div>

            {channelMode === 'existing' && (
              <>
                {form.channel_id ? (
                  <p>
                    <b>{form.channel_name}</b>{' '}
                    <span className="settings-current">{form.channel_id}</span>{' '}
                    <Button
                      label="Change"
                      type="button"
                      onClick={() =>
                        setForm(current => ({
                          ...current,
                          channel_id: '',
                          channel_name: '',
                        }))
                      }
                    />
                  </p>
                ) : (
                  <>
                    <input
                      type="text"
                      value={channelSearch}
                      placeholder="search indexed channels by name"
                      onChange={event => setChannelSearch(event.target.value)}
                    />
                    {searching && <p>Searching...</p>}
                    {!searching && channelSearch.trim() && channelResults.length === 0 && (
                      <p>
                        <i>No channel found. Use &quot;Add new&quot; for one not in the archive.</i>
                      </p>
                    )}
                    {channelResults.length > 0 && (
                      <div className="import-modal-results">
                        {channelResults.map(channel => (
                          <Button
                            key={channel.channel_id}
                            label={channel.channel_name}
                            title={channel.channel_id}
                            type="button"
                            onClick={() => selectChannel(channel)}
                          />
                        ))}
                      </div>
                    )}
                  </>
                )}
              </>
            )}

            {channelMode === 'new' && (
              <>
                <label>
                  Channel ID
                  <input
                    type="text"
                    value={form.channel_id}
                    placeholder="UCBa659QWEk1AI4Tg--mrJ2A"
                    onChange={event => setField('channel_id', event.target.value)}
                  />
                </label>
                <label>
                  Channel name
                  <input
                    type="text"
                    value={form.channel_name}
                    onChange={event => setField('channel_name', event.target.value)}
                  />
                </label>
                <p>
                  <i>
                    A channel the archive has never seen. The ID becomes the folder your media is
                    filed under, so letters, numbers, dash and underscore only.
                  </i>
                </p>
              </>
            )}
          </div>

          <label>
            Published*
            <input
              type="date"
              value={form.upload_date}
              onChange={event => setField('upload_date', event.target.value)}
            />
          </label>

          <label>
            Description
            <textarea
              rows={4}
              value={form.description}
              onChange={event => setField('description', event.target.value)}
            />
          </label>

          <label>
            Thumbnail URL
            <input
              type="url"
              value={form.thumbnail}
              placeholder="leave empty when uploading a thumbnail file"
              onChange={event => setField('thumbnail', event.target.value)}
            />
          </label>

          <label>
            Views
            <input
              type="number"
              min={0}
              value={form.view_count}
              onChange={event => setField('view_count', event.target.value)}
            />
          </label>

          <label>
            Likes
            <input
              type="number"
              min={0}
              value={form.like_count}
              onChange={event => setField('like_count', event.target.value)}
            />
          </label>
        </div>

        {error && <p className="danger-zone">{error}</p>}

        <div className="import-modal-actions">
          <Button
            label={saving ? 'Saving...' : 'Create metadata file'}
            type="button"
            disabled={!isComplete || saving}
            onClick={handleSubmit}
          />
          <Button label="Cancel" type="button" onClick={onClose} />
        </div>
      </div>
    </div>
  );
};

export default ImportMetadataModal;
