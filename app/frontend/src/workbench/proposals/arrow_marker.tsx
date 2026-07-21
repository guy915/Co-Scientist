/**
 * The arrowhead ending a directed edge, as a <marker> definition. A marker
 * reference only resolves within its own SVG, so every <svg> that draws
 * directed edges — the graph and each legend sample — renders its own
 * instance inside its <defs>, under an id unique to that SVG.
 */
export function ArrowMarker({
  id,
  size,
  units,
}: {
  id: string;
  /** Marker box edge, in the chosen units. */
  size: number;
  /** Omitted, the SVG default (`strokeWidth`) applies. */
  units?: 'userSpaceOnUse';
}) {
  return (
    <marker
      id={id}
      viewBox="0 0 10 10"
      refX="9"
      refY="5"
      markerUnits={units}
      markerWidth={size}
      markerHeight={size}
      orient="auto-start-reverse"
    >
      {/* context-stroke keeps the arrowhead the same color as the edge it
          terminates, including while dimmed. */}
      <path d="M 0 0 L 10 5 L 0 10 z" fill="context-stroke" />
    </marker>
  );
}
