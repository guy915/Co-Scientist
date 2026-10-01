// Deterministic Elo trajectories for the tournament graphics. Shape matches the
// landing page's "Ratings over one tournament" chart: eight ideas start at 1200
// (INITIAL_ELO_RATING) and one climbs clear. The winner ends at 1386, the top
// rating of the live demo run shown elsewhere in the film.
export const START_ELO = 1200;
export const TOP_ELO = 1386;
export const MATCHES = 64;
export const IDEAS = 8;

const lcg = (seed: number) => () => ((seed = (seed * 1664525 + 1013904223) >>> 0) / 2 ** 32);

export const eloSeries = (): number[][] => {
  const rnd = lcg(7);
  const drift = [2.9, 1.1, 0.6, 0.1, -0.4, -0.8, -1.2, -1.7];
  const series = drift.map(d => {
    let v = START_ELO;
    const pts = [v];
    for (let m = 1; m <= MATCHES; m++) {
      // The leader climbs steadily so its on-screen number only ever rises toward 1386.
      v += d + (rnd() - 0.5) * (d === drift[0] ? 4 : 22);
      pts.push(v);
    }
    return pts;
  });
  // Pin the winner's final value so the on-screen number is the real one.
  const w = series[0];
  const delta = (TOP_ELO - w[MATCHES]) / MATCHES;
  series[0] = w.map((v, i) => v + delta * i);
  return series;
};
