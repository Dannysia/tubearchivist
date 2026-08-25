import { useEffect, useRef, useState } from 'react';
import loadImportFiles, { ImportFileType } from '../api/loader/loadImportFiles';
import uploadImportFile from '../api/actions/uploadImportFile';
import deleteImportFile from '../api/actions/deleteImportFile';
import humanFileSize from '../functions/humanFileSize';
import Button from './Button';

type ImportFilesProps = {
  refreshToken: number;
};

type UploadStateType = {
  done: number;
  total: number;
  filename: string;
  loaded: number;
  size: number;
};

type FailureType = {
  filename: string;
  message: string;
};

// APIClient throws a bare {status, message} object on 400, not an Error,
// so instanceof alone would render these as [object Object]
const errorMessage = (err: unknown): string => {
  if (err instanceof Error) return err.message;
  if (typeof err === 'object' && err !== null && 'message' in err) {
    return String((err as { message: unknown }).message);
  }

  return String(err);
};

const ImportFiles = ({ refreshToken }: ImportFilesProps) => {
  const fileInput = useRef<HTMLInputElement>(null);

  const [files, setFiles] = useState<ImportFileType[]>([]);
  const [upload, setUpload] = useState<UploadStateType | null>(null);
  const [failures, setFailures] = useState<FailureType[]>([]);

  useEffect(() => {
    (async () => {
      const response = await loadImportFiles();

      setFiles(response.data ?? []);
    })();
  }, [refreshToken]);

  const handleUpload = async (selected: FileList | null) => {
    if (!selected || selected.length === 0) return;

    const queue = Array.from(selected);
    const failed: FailureType[] = [];
    setFailures([]);

    // one request per file, sequentially. a single request holding 200
    // videos would have no per file progress, and one rejected name would
    // take the whole batch down with it
    for (const [index, file] of queue.entries()) {
      setUpload({
        done: index,
        total: queue.length,
        filename: file.name,
        loaded: 0,
        size: file.size,
      });

      try {
        await uploadImportFile(file, loaded => {
          setUpload(current => (current ? { ...current, loaded } : current));
        });
      } catch (err) {
        failed.push({ filename: file.name, message: errorMessage(err) });
      }
    }

    setUpload(null);
    setFailures(failed);

    const response = await loadImportFiles();
    setFiles(response.data ?? []);

    // let the same selection be picked again after a failed run
    if (fileInput.current) fileInput.current.value = '';
  };

  const handleDelete = async (filename: string) => {
    if (!window.confirm(`Delete ${filename} from the import folder?`)) return;

    // only drop the row once the file is really gone, otherwise the list
    // would claim a delete that failed on disk
    try {
      const response = await deleteImportFile(filename);
      if (response.error) {
        setFailures([{ filename, message: response.error.error }]);
        return;
      }
    } catch (err) {
      setFailures([{ filename, message: errorMessage(err) }]);
      return;
    }

    setFailures([]);
    setFiles(current => current.filter(file => file.filename !== filename));
  };

  const uploadPercent = upload && upload.size > 0 ? (upload.loaded / upload.size) * 100 : 0;

  return (
    <>
      <input
        ref={fileInput}
        type="file"
        multiple
        style={{ display: 'none' }}
        accept=".mp4,.mkv,.webm,.json,.jpg,.png,.webp,.vtt"
        onChange={event => handleUpload(event.currentTarget.files)}
      />
      {upload && (
        <div className="import-upload-progress">
          <p>
            Uploading {upload.done + 1} of {upload.total}: {upload.filename} (
            {humanFileSize(upload.loaded)} / {humanFileSize(upload.size)})
          </p>
          <progress max={100} value={uploadPercent} />
        </div>
      )}
      {!upload && <Button label="Upload files" onClick={() => fileInput.current?.click()} />}
      <p>
        <i>
          Select as many files as you like. Each must be named for its 11 character video ID, either
          on its own like <span className="settings-current">hc5gku8LRTQ.mp4</span> or in brackets
          like <span className="settings-current">Some Title [hc5gku8LRTQ].mp4</span>.
        </i>
      </p>
      {failures.length > 0 && (
        <div className="import-upload-failures">
          <p className="danger-zone">{failures.length} file(s) failed:</p>
          {failures.map(failure => {
            return (
              <p key={failure.filename}>
                <b>{failure.filename}</b>: {failure.message}
              </p>
            );
          })}
        </div>
      )}

      {files.length === 0 && <p>No files staged for import.</p>}
      {files.length > 0 && (
        <div className="import-file-list">
          <div className="import-file-row">
            <span>Filename ({files.length})</span>
            <span>Size</span>
            <span>Video ID</span>
            <span></span>
          </div>
          {files.map(file => {
            return (
              <div key={file.filename} className="import-file-row">
                <span>{file.filename}</span>
                <span>{humanFileSize(file.size)}</span>
                <span>{file.video_id ?? <i>not detected</i>}</span>
                <Button
                  label="Delete"
                  title={`Delete ${file.filename}`}
                  onClick={() => handleDelete(file.filename)}
                />
              </div>
            );
          })}
        </div>
      )}
    </>
  );
};

export default ImportFiles;
