/**
 * Copyright 2026 The Co-Scientist Authors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import {describe, it, expect, vi, beforeAll} from 'vitest';
import {render, screen, fireEvent} from '@testing-library/react';
import {MdSecondaryTabs} from './MdTabs';

beforeAll(() => {
  // The md-tabs web component touches browser APIs jsdom lacks; stub them so
  // its internal effects don't raise unhandled errors during the test run.
  (window as unknown as {IntersectionObserver: unknown}).IntersectionObserver =
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    };
  if (!Element.prototype.scrollTo) {
    Element.prototype.scrollTo = () => {};
  }
});

const TABS = [{label: 'Overview'}, {label: 'Details'}];

describe('MdSecondaryTabs', () => {
  it('renders a label for each tab', () => {
    render(<MdSecondaryTabs tabs={TABS} activeIndex={0} onChange={() => {}} />);
    // Each tab is rendered twice (mobile fallback + md-secondary-tab).
    expect(screen.getAllByText('Overview').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Details').length).toBeGreaterThan(0);
  });

  it('calls onChange with the index when a mobile tab is clicked', () => {
    const onChange = vi.fn();
    render(<MdSecondaryTabs tabs={TABS} activeIndex={0} onChange={onChange} />);
    const mobileButton = screen
      .getAllByText('Details')
      .map(node => node.closest('button'))
      .find(Boolean) as HTMLButtonElement;
    fireEvent.click(mobileButton);
    expect(onChange).toHaveBeenCalledWith(1);
  });
});
