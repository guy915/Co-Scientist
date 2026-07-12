import {render, screen} from '@testing-library/react';
import {describe, expect, it} from 'vitest';
import {IntendedUseNotice} from './intended_use_notice';

describe('IntendedUseNotice', () => {
  it('states the researcher, verification, and clinical-use boundaries', () => {
    render(<IntendedUseNotice />);

    const notice = screen.getByRole('complementary', {name: 'Intended use'});
    expect(notice).toHaveTextContent('starting points');
    expect(notice).toHaveTextContent('independent verification');
    expect(notice).toHaveTextContent('Do not rely on them for clinical');
  });
});
