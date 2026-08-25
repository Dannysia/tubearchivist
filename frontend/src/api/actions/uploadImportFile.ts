import getApiUrl from '../../configuration/getApiUrl';
import getFetchCredentials from '../../configuration/getFetchCredentials';
import getCookie from '../../functions/getCookie';

export type UploadProgressType = (loaded: number, total: number) => void;

/**
 * Upload a single file to the import folder.
 *
 * Uses XMLHttpRequest rather than fetch: fetch cannot report upload
 * progress, and media files are large enough that a bare spinner leaves
 * the user with no idea whether anything is happening.
 */
const uploadImportFile = (file: File, onProgress?: UploadProgressType): Promise<void> => {
  return new Promise((resolve, reject) => {
    const formData = new FormData();
    formData.append('files', file);

    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${getApiUrl()}/api/appsettings/import-file/`);
    xhr.withCredentials = getFetchCredentials() === 'include';

    const csrfToken = getCookie('csrftoken');
    if (csrfToken) {
      xhr.setRequestHeader('X-CSRFToken', csrfToken);
    }

    xhr.upload.onprogress = event => {
      if (event.lengthComputable) {
        onProgress?.(event.loaded, event.total);
      }
    };

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve();
        return;
      }

      let message = `upload failed with status ${xhr.status}`;
      try {
        message = JSON.parse(xhr.responseText)?.error ?? message;
      } catch {
        // non JSON error body, keep the status message
      }

      reject(new Error(message));
    };

    xhr.onerror = () => reject(new Error('network error during upload'));
    xhr.onabort = () => reject(new Error('upload aborted'));

    xhr.send(formData);
  });
};

export default uploadImportFile;
