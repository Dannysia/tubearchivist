import { Fragment } from 'react';
import StatsInfoBoxItem from './StatsInfoBoxItem';
import buildResolutionPanels from '../functions/buildResolutionPanels';
import { ResolutionStatsType } from '../api/loader/loadStatsResolution';

type ResolutionStatsProps = {
  resolutionStats?: ResolutionStatsType;
  useSIUnits: boolean;
};

const ResolutionStats = ({ resolutionStats, useSIUnits }: ResolutionStatsProps) => {
  if (!resolutionStats) {
    return <p id="loading">Loading...</p>;
  }

  return buildResolutionPanels(resolutionStats, useSIUnits).map(panel => {
    return (
      <Fragment key={panel.title}>
        <StatsInfoBoxItem title={panel.title} card={panel.data} />
      </Fragment>
    );
  });
};

export default ResolutionStats;
