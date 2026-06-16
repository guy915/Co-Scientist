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

import {describe, it, expect} from 'vitest';
import {render, waitFor} from '@testing-library/react';
import {NoIndex} from './NoIndex';

describe('NoIndex', () => {
  // NoIndex renders nothing directly; it drives document head metadata via the
  // Seo effect, so assert on the document rather than the DOM tree.
  it('sets the document title to the page name suffixed with the site', async () => {
    render(<NoIndex title="Settings" />);
    await waitFor(() => expect(document.title).toBe('Settings - Co-Scientist'));
  });

  it('marks the page as noindex via the robots meta tag', async () => {
    render(<NoIndex title="Private" />);
    await waitFor(() => {
      const robots = document.head.querySelector('meta[name="robots"]');
      expect(robots).not.toBeNull();
      expect(robots).toHaveAttribute('content', 'noindex, nofollow');
    });
  });
});
