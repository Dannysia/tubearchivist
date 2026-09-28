import getApiUrl from '../../configuration/getApiUrl';

// not an APIClient call: the file can be many GB, so the browser streams it to
// disk from a plain link rather than buffering it through fetch
const importFileUrl = (filename: string): string =>
  `${getApiUrl()}/api/appsettings/import-file/${encodeURIComponent(filename)}/`;

export default importFileUrl;
