import getApiUrl from '../../configuration/getApiUrl';

// the download url for a staged import file. Not an APIClient call: the
// file can be many GB, so it is handed to the browser as a plain link
// and streamed to disk rather than buffered through fetch.
const importFileUrl = (filename: string): string =>
  `${getApiUrl()}/api/appsettings/import-file/${encodeURIComponent(filename)}/`;

export default importFileUrl;
