import { useState } from 'react';
import Button from './Button';
import formatDate from '../functions/formatDates';
import getApiUrl from '../configuration/getApiUrl';
import { HistoryVersionType } from '../api/loader/loadVideoHistory';

type FieldHistoryProps = {
  label: string;
  versions: HistoryVersionType[] | undefined;
  kind?: 'text' | 'image';
};

const seenRange = (version: HistoryVersionType) => {
  const from = version.first_seen ? formatDate(version.first_seen * 1000) : 'download';
  if (version.replaced === null) {
    return `Current, since ${from}`;
  }

  return `${from} until ${formatDate(version.replaced * 1000)}`;
};

const FieldHistory = ({ label, versions, kind = 'text' }: FieldHistoryProps) => {
  const [open, setOpen] = useState(false);

  if (!versions || versions.length === 0) {
    return null;
  }

  return (
    <>
      <Button
        className="field-history-toggle"
        label={open ? `Hide ${label} history` : `${label} history (${versions.length})`}
        onClick={() => setOpen(!open)}
      />
      {open && (
        <div className="field-history">
          {versions.map(version => (
            <div
              key={`${version.first_seen}-${version.replaced}`}
              className="field-history-version"
            >
              <p className="field-history-dates">{seenRange(version)}</p>
              {kind === 'image' &&
                (version.image_url ? (
                  <img src={`${getApiUrl()}${version.image_url}`} alt={`${label} version`} />
                ) : (
                  <p>Image not kept</p>
                ))}
              {kind === 'text' && <p className="field-history-text">{version.value ?? '(none)'}</p>}
            </div>
          ))}
        </div>
      )}
    </>
  );
};

export default FieldHistory;
