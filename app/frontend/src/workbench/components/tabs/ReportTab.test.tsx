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
import {ReportTab} from './ReportTab';

describe('ReportTab', () => {
  it('shows the pending message when no report exists yet', () => {
    // The report=null branch renders without any markdown fetch.
    render(<ReportTab runId="r1" report={null} safety={[]} />);
    expect(
      screen.getByText('The report appears once the workflow finishes.'),
    ).toBeInTheDocument();
  });
});
