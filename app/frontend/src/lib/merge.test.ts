import {describe, expect, it} from 'vitest';

import {mergeByIdNewestFirst} from './merge';

interface Item {
  id: string;
  updated_at: number;
  tag?: string;
}

const id = (i: Item) => i.id;
const updatedAt = (i: Item) => i.updated_at;

describe('mergeByIdNewestFirst', () => {
  it('orders by updated_at descending', () => {
    const merged = mergeByIdNewestFirst(
      [
        {id: 'a', updated_at: 1},
        {id: 'b', updated_at: 3},
        {id: 'c', updated_at: 2},
      ],
      id,
      updatedAt,
    );
    expect(merged.map(i => i.id)).toEqual(['b', 'c', 'a']);
  });

  it('keeps the later item when ids collide', () => {
    const merged = mergeByIdNewestFirst(
      [
        {id: 'a', updated_at: 1, tag: 'first'},
        {id: 'a', updated_at: 5, tag: 'second'},
      ],
      id,
      updatedAt,
    );
    expect(merged).toHaveLength(1);
    expect(merged[0].tag).toBe('second');
  });

  it('returns an empty array for no items', () => {
    expect(mergeByIdNewestFirst([], id, updatedAt)).toEqual([]);
  });
});
