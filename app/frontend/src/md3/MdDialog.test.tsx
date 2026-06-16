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

import {describe, it, expect, beforeAll} from 'vitest';
import {render, screen} from '@testing-library/react';
import {MdDialog} from './MdDialog';

beforeAll(() => {
  // The md-dialog web component constructs an IntersectionObserver in its
  // first update; jsdom lacks it, so stub it to avoid unhandled rejections.
  (window as unknown as {IntersectionObserver: unknown}).IntersectionObserver =
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    };
});

describe('MdDialog', () => {
  // Rendered closed: the headline, body, and actions are slotted into the
  // light DOM regardless of open state, so they are queryable without
  // invoking the web component's show() (which is unreliable in jsdom).
  it('renders the headline, children, and actions content', () => {
    render(
      <MdDialog
        open={false}
        onClose={() => {}}
        headline="My headline"
        actions={<button type="button">OK</button>}
      >
        <p>Dialog body</p>
      </MdDialog>,
    );
    expect(screen.getByText('My headline')).toBeInTheDocument();
    expect(screen.getByText('Dialog body')).toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'OK'})).toBeInTheDocument();
  });

  it('renders the body even without a headline or actions', () => {
    render(
      <MdDialog open={false} onClose={() => {}}>
        <p>Just a body</p>
      </MdDialog>,
    );
    expect(screen.getByText('Just a body')).toBeInTheDocument();
  });
});
