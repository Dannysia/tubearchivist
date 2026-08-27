import { useCallback, useEffect, useState } from 'react';
import SettingsNavigation from '../components/SettingsNavigation';
import Notifications from '../components/Notifications';
import Pagination from '../components/Pagination';
import PaginationDummy from '../components/PaginationDummy';
import Button from '../components/Button';
import InputConfig from '../components/InputConfig';
import LoadingIndicator from '../components/LoadingIndicator';
import loadLogs, { LogEntryType, LogLevel, LogResponseType } from '../api/loader/loadLogs';
import deleteLogs from '../api/actions/deleteLogs';
import loadAppsettingsConfig, { AppSettingsConfigType } from '../api/loader/loadAppsettingsConfig';
import updateAppsettingsConfig from '../api/actions/updateAppsettingsConfig';
import { ApiResponseType } from '../functions/APIClient';
import { useUserConfigStore } from '../stores/UserConfigStore';
import formatDate from '../functions/formatDates';

const LEVEL_OPTIONS: { value: LogLevel | ''; label: string }[] = [
  { value: '', label: 'All levels' },
  { value: 'error', label: 'Errors only' },
  { value: 'info', label: 'Info' },
];

const SettingsLogs = () => {
  const { userConfig } = useUserConfigStore();
  const showHelpText = userConfig.show_help_text;

  const [logResponse, setLogResponse] = useState<ApiResponseType<LogResponseType>>();
  const [appSettingsConfig, setAppSettingsConfig] = useState<AppSettingsConfigType>();
  const [page, setPage] = useState(0);
  const [level, setLevel] = useState<LogLevel | ''>('');
  const [taskName, setTaskName] = useState('');
  const [searchInput, setSearchInput] = useState('');
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [clearing, setClearing] = useState(false);
  const [showClearConfirm, setShowClearConfirm] = useState(false);
  const [refreshNonce, setRefreshNonce] = useState(0);
  const [retentionDays, setRetentionDays] = useState<number | null>(null);

  const { data: logData, error: logError } = logResponse ?? {};
  const entries = logData?.data ?? [];
  const paginate = logData?.paginate;

  const refresh = useCallback(() => setRefreshNonce(nonce => nonce + 1), []);

  useEffect(() => {
    (async () => {
      setLoading(true);
      const response = await loadLogs(
        'notification',
        page,
        level || null,
        taskName || null,
        search,
      );
      setLogResponse(response);
      setLoading(false);
    })();
  }, [page, level, taskName, search, refreshNonce]);

  useEffect(() => {
    (async () => {
      const { data } = await loadAppsettingsConfig();
      setAppSettingsConfig(data);
      setRetentionDays(data?.application.log_retention_days ?? null);
    })();
  }, [refreshNonce]);

  const handleUpdateConfig = async (
    configKey: string,
    configValue: string | boolean | number | null,
  ) => {
    const [group, key] = configKey.split('.');
    await updateAppsettingsConfig({
      [group]: { [key]: configValue },
    } as Partial<AppSettingsConfigType>);
    refresh();
  };

  const handleClear = async () => {
    setClearing(true);
    setShowClearConfirm(false);
    await deleteLogs('notification');
    setClearing(false);
    setPage(0);
    refresh();
  };

  // aggregated over the whole log rather than the visible page, so the
  // list stays put when a task is picked and covers tasks whose entries
  // all sit on a later page
  const taskOptions = logData?.tasks ?? [];

  const retentionNote = appSettingsConfig
    ? `Entries older than ${appSettingsConfig.application.log_retention_days} days are pruned once a day.`
    : null;

  return (
    <>
      <title>TA | Logs</title>
      <div className="boxed-content">
        <SettingsNavigation />
        <Notifications pageName={'all'} />

        <div className="title-bar">
          <h1>Logs</h1>
        </div>

        <div className="info-box">
          <div className="info-box-item">
            <h2 id="notifications">Task notifications</h2>
            {showHelpText && (
              <div className="help-text">
                <p>
                  What each background task did, kept after the on-screen message has gone. Only
                  runs that did something are recorded: a task that found nothing to do is not
                  listed. {retentionNote}
                </p>
              </div>
            )}

            <div className="settings-box-wrapper">
              <div>
                <p>Keep entries for</p>
              </div>
              <InputConfig
                type="number"
                name="application.log_retention_days"
                value={retentionDays}
                setValue={setRetentionDays}
                oldValue={appSettingsConfig?.application.log_retention_days ?? null}
                updateCallback={handleUpdateConfig}
              />
            </div>

            <div className="settings-box-wrapper">
              <div>
                <p>Filter</p>
              </div>
              <div>
                <select
                  value={level}
                  onChange={event => {
                    setLevel(event.target.value as LogLevel | '');
                    setPage(0);
                  }}
                >
                  {LEVEL_OPTIONS.map(option => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>{' '}
                <select
                  value={taskName}
                  onChange={event => {
                    setTaskName(event.target.value);
                    setPage(0);
                  }}
                >
                  <option value="">All tasks</option>
                  {taskOptions.map(option => (
                    <option key={option.task_name} value={option.task_name}>
                      {option.task_title || option.task_name}
                    </option>
                  ))}
                </select>{' '}
                <input
                  type="text"
                  value={searchInput}
                  placeholder="Search messages"
                  onChange={event => setSearchInput(event.target.value)}
                  onKeyDown={event => {
                    if (event.key === 'Enter') {
                      setSearch(searchInput);
                      setPage(0);
                    }
                  }}
                />{' '}
                <Button
                  type="button"
                  label="Search"
                  onClick={() => {
                    setSearch(searchInput);
                    setPage(0);
                  }}
                />{' '}
                <Button type="button" label="Refresh" onClick={refresh} />{' '}
                {showClearConfirm ? (
                  /* clears the whole notification log, not only the
                     entries the current filter has in view */
                  <>
                    <Button
                      type="button"
                      className="danger-button"
                      label="Confirm clear all"
                      onClick={handleClear}
                    />{' '}
                    <Button
                      type="button"
                      label="Cancel"
                      onClick={() => setShowClearConfirm(false)}
                    />
                  </>
                ) : (
                  <Button
                    type="button"
                    className="danger-button"
                    label={clearing ? 'Clearing...' : 'Clear all'}
                    onClick={() => setShowClearConfirm(true)}
                  />
                )}
              </div>
            </div>

            {loading && <LoadingIndicator />}

            {!loading && logError && (
              <p>Could not read the log: {logError.error ?? 'unknown error'}</p>
            )}

            {!loading && !logError && entries.length === 0 && (
              <p>
                {level || taskName || search
                  ? 'No entry matches the current filter.'
                  : 'Nothing logged yet. Entries appear here once a background task completes or fails.'}
              </p>
            )}

            {!loading && !logError && entries.length > 0 && (
              <div className="log-table-wrapper">
                <table className="log-table">
                  <thead>
                    <tr>
                      <th>When</th>
                      <th>Task</th>
                      <th>Event</th>
                      <th>Message</th>
                    </tr>
                  </thead>
                  <tbody>
                    {entries.map((entry: LogEntryType) => (
                      <tr key={entry.id} className={`log-row log-${entry.level}`}>
                        <td title={new Date(entry.timestamp * 1000).toISOString()}>
                          {formatDate(entry.timestamp * 1000, true)}
                        </td>
                        <td>{entry.task_title || entry.task_name || '—'}</td>
                        <td>{entry.event || '—'}</td>
                        <td className="log-message">{entry.message}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>

        {paginate && entries.length > 0 ? (
          <Pagination pagination={paginate} setPage={setPage} />
        ) : (
          <PaginationDummy />
        )}
      </div>
    </>
  );
};

export default SettingsLogs;
