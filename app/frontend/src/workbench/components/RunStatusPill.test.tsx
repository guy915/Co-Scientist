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
import {render, screen} from '@testing-library/react';
import {RunStatusPill} from './RunStatusPill';

describe('RunStatusPill', () => {
  it('renders the label for a known status', () => {
    render(<RunStatusPill status="running" />);
    expect(screen.getByText('Running')).toBeInTheDocument();
  });

  it('renders the safety label for the blocked status', () => {
    render(<RunStatusPill status="blocked" />);
    expect(screen.getByText('Blocked (safety)')).toBeInTheDocument();
  });
});
