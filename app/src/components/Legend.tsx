import { RAMP } from './MapView';

export default function Legend() {
  return (
    <div className="map-card map-card-bottomleft legend">
      <span>low</span>
      {RAMP.map((c, i) => (
        <span key={i} className="swatch" style={{ background: `rgb(${c[0]},${c[1]},${c[2]})` }} />
      ))}
      <span>high</span>
      <span className="swatch" style={{ background: 'rgb(70,70,78)', marginLeft: 10 }} />
      <span>masked</span>
    </div>
  );
}
