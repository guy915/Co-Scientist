// Beat times (s) of the soundtrack, from librosa's beat tracker. The track
// drifts around 94-96 bpm, so a fixed grid lands up to a frame off; these are
// the detected beats. Downbeats are every 4th from index 1, and the bass drops
// out on several of them (8.31, 10.87, 18.51, 28.70, 31.23, 38.87, 41.42 s):
// those stabs carry the film's biggest visual hits.
const TIMES = [
  0.09, 0.7, 1.35, 1.97, 2.62, 3.25, 3.88, 4.5, 5.13, 5.78, 6.43, 7.06, 7.69, 8.31, 8.96, 9.59, 10.24, 10.87,
  11.52, 12.14, 12.77, 13.42, 14.07, 14.7, 15.33, 15.95, 16.6, 17.23, 17.88, 18.51, 19.16, 19.78, 20.41, 21.06,
  21.71, 22.34, 22.96, 23.61, 24.24, 24.87, 25.52, 26.15, 26.8, 27.42, 28.05, 28.7, 29.33, 29.95, 30.6, 31.23,
  31.88, 32.51, 33.16, 33.79, 34.41, 35.06, 35.69, 36.34, 36.99, 37.59, 38.24, 38.87, 39.52, 40.15, 40.77, 41.42,
  42.07, 42.7, 43.33, 43.98, 44.63, 45.26, 45.88, 46.53, 47.18, 47.81, 48.41, 49.06, 49.71, 50.36, 50.99, 51.62,
  52.27, 52.9, 53.55,
];

/** Global frame of beat `i` (30 fps); fractional `i` lands between beats, e.g. 2.5 is an eighth note. */
export const B = (i: number) => {
  const lo = Math.min(Math.floor(i), TIMES.length - 2);
  return Math.round((TIMES[lo] + (TIMES[lo + 1] - TIMES[lo]) * (i - lo)) * 30);
};

/** The soundtrack is 54.15 s; the film is exactly as long. */
export const LAUNCH_FRAMES = 1624;
