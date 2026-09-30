import { useEffect, useState } from 'react';
import Button from './Button';
import createImportMetadata, { ImportMetadataType } from '../api/actions/createImportMetadata';
import { ImportFileType } from '../api/loader/loadImportFiles';
import searchChannels from '../api/loader/searchChannels';
import loadArchiveMetadata from '../api/loader/loadArchiveMetadata';
import { ChannelType } from '../pages/Channels';

type ImportMetadataModalProps = {
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

const REQUIRED_LABELS: { field: keyof FormState; label: string }[] = [
  { field: 'title', label: 'title' },
  { field: 'channel_id', label: 'channel ID' },
  { field: 'channel_name', label: 'channel name' },
  { field: 'upload_date', label: 'published date' },
];

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

  const [looking, setLooking] = useState(false);
  const [lookupMessage, setLookupMessage] = useState('');
  const [lookupError, setLookupError] = useState('');

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
    setForm(current => ({ ...current, channel_id: '', channel_name: '' }));
    setChannelSearch('');
    setChannelResults([]);
  };

  const setField = (field: keyof FormState, value: string) => {
    setForm(current => ({ ...current, [field]: value }));
    if (field === 'video_id') {
      setLookupMessage('');
      setLookupError('');
    }
  };

  const handleLookup = async () => {
    const videoId = form.video_id.trim();

    setLooking(true);
    setLookupMessage('');
    setLookupError('');

    try {
      const response = await loadArchiveMetadata(videoId);
      if (response.error || !response.data) {
        setLookupError(response.error?.error ?? 'no metadata came back');
        return;
      }

      const found = response.data;
      const fill = (current: string, value: string | number | null | undefined) =>
        current || (value === null || value === undefined ? '' : String(value));

      const merge = (current: FormState): FormState => ({
        ...current,
        video_id: videoId,
        title: fill(current.title, found.title),
        channel_id: fill(current.channel_id, found.channel_id),
        channel_name: fill(current.channel_name, found.channel_name),
        upload_date: fill(current.upload_date, found.upload_date),
        description: fill(current.description, found.description),
        thumbnail: fill(current.thumbnail, found.thumbnail),
        view_count: fill(current.view_count, found.view_count),
        like_count: fill(current.like_count, found.like_count),
      });

      let stale = false;
      setForm(current => {
        if (current.video_id.trim() !== videoId) {
          stale = true;
          return current;
        }

        return merge(current);
      });

      if (stale) return;

      const filled = merge(form);
      const stillEmpty = REQUIRED_LABELS.filter(({ field }) => !filled[field]).map(
        ({ label }) => label,
      );
      setLookupMessage(
        stillEmpty.length
          ? `Found "${found.title}" on the Internet Archive. Still needed: ${stillEmpty.join(', ')}.`
          : `Found "${found.title}" on the Internet Archive.`,
      );
    } catch (err) {
      setLookupError(errorMessage(err));
    } finally {
      setLooking(false);
    }
  };

  const isComplete =
    form.video_id.length === 11 && REQUIRED_LABELS.every(({ field }) => !!form[field]);

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
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="import-modal" role="dialog" aria-modal="true">
        <h2>Generate metadata file</h2>
        <p>
          <i>
            Writes an <span className="settings-current">.info.json</span> into the import folder,
            named to match the staged media file it belongs to. Use this when the video is no longer
            on YouTube, so there is nothing to look the metadata up from.
          </i>
        </p>
        <p>
          <i>
            These values are a fallback. The import still asks YouTube first, and fills in from this
            file where YouTube has nothing to give - which for a removed video is everything but the
            id.
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

          <div className="import-modal-lookup">
            <Button
              label={looking ? 'Searching the Internet Archive...' : 'Look up on Internet Archive'}
              title="Fill this form from an archived copy of the YouTube watch page"
              type="button"
              disabled={form.video_id.trim().length !== 11 || looking}
              onClick={handleLookup}
            />
            <p>
              <i>
                The Wayback Machine kept a copy of a lot of watch pages before the videos came down.
                This reads one back and fills in whatever it held. Anything already typed in is left
                alone.
              </i>
            </p>
            {lookupMessage && <p>{lookupMessage}</p>}
            {lookupError && <p className="danger-zone">{lookupError}</p>}
          </div>

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

          <p>
            <i>
              Leave the counts empty if you do not know them. The video shows them as{' '}
              <span className="settings-current">unknown</span> rather than claiming zero. A capture
              rarely has them.
            </i>
          </p>
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
