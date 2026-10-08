import {render, screen} from '@testing-library/react';
import {expect, it} from 'vitest';
import {Chip} from './chip';

it('draws card metadata as small-radius tags and labels as pills', () => {
  render(
    <>
      <Chip shape="tag">Oct 7, 2026</Chip>
      <Chip>Offline mode</Chip>
    </>,
  );
  const tag = screen.getByText('Oct 7, 2026');
  expect(tag.className).toContain('rounded-md');
  expect(tag.className).not.toContain('rounded-full');
  expect(screen.getByText('Offline mode').className).toContain('rounded-full');
});
