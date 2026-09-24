import type {RunAttribute, RunCriterion} from '@/api/runs';

// Joins values with a trailing "or" ("A, B, or C"), matching the run plan's
// categorical-attribute punctuation.
function joinWithOr(values: string[]): string {
  if (values.length === 1) return values[0];
  if (values.length === 2) return `${values[0]} or ${values[1]}`;
  return `${values.slice(0, -1).join(', ')}, or ${values[values.length - 1]}`;
}

function scaledDisplayString(
  name: string,
  scale: {'1'?: string; '3'?: string; '5'?: string},
): string {
  const anchors = (['1', '3', '5'] as const)
    .filter(point => scale[point])
    .map(point => `${point}: ${scale[point]}`);
  return anchors.length ? `${name}: 1-5 scale (${anchors.join(', ')})` : name;
}

function categoricalDisplayString(name: string, values: string[]): string {
  const options = (values ?? []).filter(Boolean);
  return options.length ? `${name} (${joinWithOr(options)})` : name;
}

// Displays either legacy free prose or the structured run-attribute shape.
export function attributeDisplayString(item: RunAttribute): string {
  if (typeof item === 'string') return item;
  if ('scale' in item) return scaledDisplayString(item.name, item.scale);
  return categoricalDisplayString(item.name, item.values);
}

export function criterionDisplayString(item: RunCriterion): string {
  if (typeof item === 'string') return item;
  return `${item.name}: ${item.value}`;
}
