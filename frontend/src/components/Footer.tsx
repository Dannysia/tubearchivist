import { Link } from 'react-router-dom';
import Routes from '../configuration/routes/RouteList';
import { useAuthStore } from '../stores/AuthDataStore';
import formatDate from '../functions/formatDates';

const Footer = () => {
  const currentYear = new Date().getFullYear();
  const { auth } = useAuthStore();
  // upstream's release number, which says what mainline base this is
  const version = auth?.version;
  // and which build of this fork is actually running, absent on an
  // image built without the build args
  const buildSha = auth?.build_sha;
  const buildDate = auth?.build_date;
  const taUpdate = auth?.ta_update;

  return (
    <div className="footer">
      <div className="boxed-content">
        <span>© 2021 - {currentYear} </span>
        <span>TubeArchivist </span>
        <span>{version} </span>
        {buildSha && (
          // the visible date is rendered in the viewer's timezone, the
          // title keeps the canonical instant for comparing against
          // docker or a build log, labelled so it cannot be read as local
          <span title={buildDate ? `built ${buildDate} (UTC)` : undefined}>
            · {buildSha}
            {buildDate && ` · ${formatDate(buildDate, true)}`}{' '}
          </span>
        )}
        {taUpdate?.version && (
          <>
            <span className="danger-zone">
              {taUpdate.version} available
              {taUpdate.is_breaking && <span className="danger-zone">Breaking Changes!</span>}
            </span>{' '}
            <span>
              <a
                href={`https://github.com/tubearchivist/tubearchivist/releases/tag/${taUpdate.version}`}
                target="_blank"
              >
                Release Page
              </a>{' '}
              |{' '}
            </span>
          </>
        )}
        <span>
          <Link to={Routes.About}>About</Link> |{' '}
          <a href="https://github.com/Dannysia/tubearchivist" target="_blank">
            Fork
          </a>{' '}
          |{' '}
          <a href="https://github.com/tubearchivist/tubearchivist" target="_blank">
            Upstream
          </a>{' '}
          |{' '}
          <a href="https://www.tubearchivist.com/discord" target="_blank">
            Discord
          </a>{' '}
          | <a href="https://www.reddit.com/r/TubeArchivist/">Reddit</a>
        </span>
      </div>
    </div>
  );
};

export default Footer;
