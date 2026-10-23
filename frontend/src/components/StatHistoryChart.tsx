import { KeyboardEvent, PointerEvent, useEffect, useRef, useState } from 'react';
import Button from './Button';
import formatDate from '../functions/formatDates';
import formatNumbers from '../functions/formatNumbers';
import { HistoryPointType } from '../api/loader/loadVideoHistory';

type StatHistoryChartProps = {
  title: string;
  points: HistoryPointType[];
};

const HEIGHT = 170;
const MARGIN = { top: 14, right: 84, bottom: 30, left: 70 };
const Y_TICKS = 4;

const niceStep = (range: number) => {
  const rough = range / Y_TICKS;
  const magnitude = 10 ** Math.floor(Math.log10(rough));
  const residual = rough / magnitude;
  const nice = residual > 5 ? 10 : residual > 2 ? 5 : residual > 1 ? 2 : 1;
  return nice * magnitude;
};

const yDomain = (values: number[]) => {
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || Math.max(Math.abs(max) * 0.1, 1);
  const step = niceStep(span);
  const lower = Math.max(0, Math.floor((min - span * 0.05) / step) * step);
  const upper = Math.ceil((max + span * 0.05) / step) * step;
  const ticks = [];
  for (let tick = lower; tick <= upper + step / 2; tick += step) {
    ticks.push(tick);
  }
  return { lower, upper, ticks };
};

const StatHistoryChart = ({ title, points }: StatHistoryChartProps) => {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(560);
  const [active, setActive] = useState<number | null>(null);
  const [showTable, setShowTable] = useState(false);

  useEffect(() => {
    const element = wrapRef.current;
    if (!element) {
      return;
    }

    const observer = new ResizeObserver(entries => {
      setWidth(Math.max(280, entries[0].contentRect.width));
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const plotWidth = width - MARGIN.left - MARGIN.right;
  const plotHeight = HEIGHT - MARGIN.top - MARGIN.bottom;
  const first = points[0].timestamp;
  const last = points[points.length - 1].timestamp;
  const { lower, upper, ticks } = yDomain(points.map(point => point.value));

  const xOf = (timestamp: number) =>
    MARGIN.left +
    (last === first ? plotWidth / 2 : ((timestamp - first) / (last - first)) * plotWidth);
  const yOf = (value: number) =>
    MARGIN.top + plotHeight - ((value - lower) / (upper - lower || 1)) * plotHeight;

  const path = points
    .map((point, index) => `${index ? 'L' : 'M'}${xOf(point.timestamp)},${yOf(point.value)}`)
    .join(' ');
  const end = points[points.length - 1];
  const activePoint = active === null ? null : points[active];

  const handlePointerMove = (event: PointerEvent<SVGRectElement>) => {
    const box = event.currentTarget.ownerSVGElement?.getBoundingClientRect();
    if (!box) {
      return;
    }

    const x = event.clientX - box.left;
    let nearest = 0;
    points.forEach((point, index) => {
      if (Math.abs(xOf(point.timestamp) - x) < Math.abs(xOf(points[nearest].timestamp) - x)) {
        nearest = index;
      }
    });
    setActive(nearest);
  };

  const handleKeyDown = (event: KeyboardEvent<SVGSVGElement>) => {
    if (event.key === 'ArrowLeft') {
      setActive(current => Math.max(0, (current ?? points.length) - 1));
    } else if (event.key === 'ArrowRight') {
      setActive(current => Math.min(points.length - 1, (current ?? -1) + 1));
    }
  };

  return (
    <div className="stat-history-chart">
      <h4>{title}</h4>
      <div ref={wrapRef} className="stat-history-plot">
        <svg
          width={width}
          height={HEIGHT}
          role="img"
          aria-label={`${title}: ${points.length} recorded values, latest ${formatNumbers(end.value)}`}
          tabIndex={0}
          onKeyDown={handleKeyDown}
          onFocus={() => setActive(points.length - 1)}
          onBlur={() => setActive(null)}
        >
          {ticks.map(tick => (
            <g key={tick}>
              <line
                className="stat-history-grid"
                x1={MARGIN.left}
                x2={MARGIN.left + plotWidth}
                y1={yOf(tick)}
                y2={yOf(tick)}
              />
              <text
                className="stat-history-axis"
                x={MARGIN.left - 8}
                y={yOf(tick)}
                textAnchor="end"
                dominantBaseline="middle"
              >
                {formatNumbers(tick)}
              </text>
            </g>
          ))}
          <text className="stat-history-axis" x={MARGIN.left} y={HEIGHT - 8} textAnchor="start">
            {formatDate(first * 1000)}
          </text>
          {last !== first && (
            <text
              className="stat-history-axis"
              x={MARGIN.left + plotWidth}
              y={HEIGHT - 8}
              textAnchor="end"
            >
              {formatDate(last * 1000)}
            </text>
          )}

          {activePoint && (
            <line
              className="stat-history-crosshair"
              x1={xOf(activePoint.timestamp)}
              x2={xOf(activePoint.timestamp)}
              y1={MARGIN.top}
              y2={MARGIN.top + plotHeight}
            />
          )}
          <path className="stat-history-line" d={path} />
          {points.map((point, index) => (
            <circle
              key={point.timestamp}
              className="stat-history-marker"
              cx={xOf(point.timestamp)}
              cy={yOf(point.value)}
              r={active === index ? 5 : 4}
            />
          ))}
          <text
            className="stat-history-end"
            x={xOf(end.timestamp) + 10}
            y={yOf(end.value)}
            dominantBaseline="middle"
          >
            {formatNumbers(end.value)}
          </text>
          <rect
            x={MARGIN.left - 12}
            y={MARGIN.top}
            width={plotWidth + 24}
            height={plotHeight}
            fill="transparent"
            onPointerMove={handlePointerMove}
            onPointerLeave={() => setActive(null)}
          />
        </svg>
        {activePoint && (
          <div
            className="stat-history-tooltip"
            style={{
              left: Math.min(xOf(activePoint.timestamp) + 12, width - 150),
              top: Math.max(0, yOf(activePoint.value) - 44),
            }}
          >
            <strong>{formatNumbers(activePoint.value)}</strong>
            <span>{formatDate(activePoint.timestamp * 1000, true)}</span>
          </div>
        )}
      </div>
      <Button
        className="field-history-toggle"
        label={showTable ? 'Hide table' : 'Show table'}
        onClick={() => setShowTable(!showTable)}
      />
      {showTable && (
        <table className="stat-history-table">
          <thead>
            <tr>
              <th>Recorded</th>
              <th>{title}</th>
            </tr>
          </thead>
          <tbody>
            {[...points].reverse().map(point => (
              <tr key={point.timestamp}>
                <td>{formatDate(point.timestamp * 1000, true)}</td>
                <td>{formatNumbers(point.value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
};

export default StatHistoryChart;
