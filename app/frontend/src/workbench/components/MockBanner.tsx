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

import '@material/web/icon/icon.js';
import {useEffect, useState} from 'react';
import {getSystemStatus, type SystemStatus} from '@/api/runs';

export function MockBanner() {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  useEffect(() => {
    let cancelled = false;
    getSystemStatus()
      .then(s => {
        if (!cancelled) setStatus(s);
      })
      .catch(() => {
        /* swallow — banner is non-critical */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!status) return null;
  if (!status.mock_mode) {
    return (
      <div
        className="text-xs px-6 py-1 border-t"
        style={{
          backgroundColor: 'var(--md-sys-color-secondary-container)',
          color: 'var(--md-sys-color-on-surface-variant)',
          borderColor: 'var(--md-sys-color-outline-variant)',
        }}
      >
        Live engine mode &middot; provider: <strong>{status.provider}</strong>{' '}
        &middot; model: <strong>{status.model_name}</strong>
      </div>
    );
  }
  return (
    <div
      role="status"
      className="text-xs px-6 py-1.5 border-t flex items-center gap-2"
      style={{
        backgroundColor:
          'color-mix(in srgb, var(--color-th-warning) 18%, transparent)',
        color: 'var(--md-sys-color-on-surface)',
        borderColor: 'var(--md-sys-color-outline-variant)',
      }}
    >
      <md-icon aria-hidden="true" style={{fontSize: '14px'}}>
        warning
      </md-icon>
      <span>
        <strong>Mock Mode</strong> — no LLM provider key detected. The workflow
        runs deterministic offline data so the full UI surface is exercisable.
        Set <code>GEMINI_API_KEY</code> / <code>OPENAI_API_KEY</code> /{' '}
        <code>ANTHROPIC_API_KEY</code> in <code>.env</code> to use the real
        engine.
      </span>
    </div>
  );
}
