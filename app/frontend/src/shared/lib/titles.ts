import {conciseTitle} from './text';

// A stored title wins once trimmed. Otherwise each surface shortens the goal
// its own way; the report header deliberately shows the whole goal.
export function displayTitle(
  title: string | null | undefined,
  goal: string,
  shorten: (goal: string) => string = conciseTitle,
): string {
  return title?.trim() || shorten(goal);
}
