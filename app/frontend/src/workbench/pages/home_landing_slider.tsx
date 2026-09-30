// The pill that slides between the selected items of a segmented track: the
// section rail and the tier picker. See useSlidingIndicator.

import {type IndicatorBox} from './home_landing_hooks';

/** Renders the sliding pill for a measured selection, or nothing yet. */
export function SlidingPill({box}: {box: IndicatorBox | null}) {
  if (!box) return null;
  return (
    <span
      aria-hidden="true"
      className={
        box.animate ? 'ucs-landing-slider is-animated' : 'ucs-landing-slider'
      }
      style={{width: box.width, transform: `translateX(${box.left}px)`}}
    />
  );
}
