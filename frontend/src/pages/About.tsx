const FORK_REPO = 'https://github.com/Dannysia/tubearchivist';
const UPSTREAM_REPO = 'https://github.com/tubearchivist/tubearchivist';

const About = () => {
  return (
    <>
      <title>TA | About</title>

      <div className="boxed-content">
        <div className="title-bar">
          <h1>About The Tube Archivist</h1>
        </div>
        <div className="about-section">
          <h2>This Instance</h2>
          <p>
            This runs a{' '}
            <a href={FORK_REPO} target="_blank">
              personal fork
            </a>{' '}
            of Tube Archivist, with added downscaling, remote encode workers, web UI media import
            and extra statistics. The version and build it is running are shown in the footer.
          </p>
          <p>
            Anything specific to this fork — including the features listed above — belongs in the{' '}
            <a href={`${FORK_REPO}/issues`} target="_blank">
              fork&apos;s issue tracker
            </a>
            , not upstream&apos;s. Pull requests are welcome there, though they are not a priority.
          </p>
        </div>
        <div className="about-section">
          <h2>Upstream</h2>
          <p>
            All of this is built on{' '}
            <a href={UPSTREAM_REPO} target="_blank">
              tubearchivist/tubearchivist
            </a>
            , where the credit for the project belongs. Their{' '}
            <a href="https://docs.tubearchivist.com" target="_blank">
              user guide
            </a>{' '}
            still documents everything this fork has not changed.
          </p>
          <p>
            The{' '}
            <a href="https://www.tubearchivist.com/discord" target="_blank">
              Discord
            </a>{' '}
            and{' '}
            <a href={`${UPSTREAM_REPO}#roadmap`} target="_blank">
              roadmap
            </a>{' '}
            are upstream&apos;s and describe the upstream project. Please do not take problems
            caused by this fork to either.
          </p>
        </div>
        <div className="about-section">
          <h2>Donate</h2>
          <p>
            Support upstream rather than this fork —{' '}
            <a href="https://github.com/sponsors/bbilly1" target="_blank">
              here are some links
            </a>{' '}
            if you want to buy them a coffee. Thank you for your support!
          </p>
        </div>
      </div>
    </>
  );
};

export default About;
