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

import {describe, it, expect, vi} from 'vitest';
import {render, screen} from '@testing-library/react';
import {userEvent} from '@testing-library/user-event';
import {Button} from './button';

describe('Button', () => {
  it('renders its children as the label', () => {
    render(<Button>Click me</Button>);
    expect(screen.getByText('Click me')).toBeInTheDocument();
  });

  it('invokes onClick when clicked', async () => {
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Press</Button>);
    await userEvent.click(screen.getByText('Press'));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('renders the default variant as a filled button element', () => {
    const {container} = render(<Button>Default</Button>);
    expect(container.querySelector('md-filled-button')).not.toBeNull();
  });

  it('renders the outline variant as an outlined button element', () => {
    const {container} = render(<Button variant="outline">Outlined</Button>);
    expect(container.querySelector('md-outlined-button')).not.toBeNull();
  });

  it('renders the secondary variant as a filled tonal button element', () => {
    const {container} = render(<Button variant="secondary">Tonal</Button>);
    expect(container.querySelector('md-filled-tonal-button')).not.toBeNull();
  });

  it('renders the icon size as an icon button element', () => {
    const {container} = render(<Button size="icon">x</Button>);
    expect(container.querySelector('md-icon-button')).not.toBeNull();
  });

  it('passes through a custom className as the element class', () => {
    const {container} = render(<Button className="my-class">X</Button>);
    expect(container.querySelector('.my-class')).not.toBeNull();
  });
});
