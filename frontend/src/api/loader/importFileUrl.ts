import getApiUrl from '../../configuration/getApiUrl';

// a plain link, so the browser streams the file to disk
const importFileUrl = (filename: string): string =>
  `${getApiUrl()}/api/appsettings/import-file/${encodeURIComponent(filename)}/`;

export default importFileUrl;
