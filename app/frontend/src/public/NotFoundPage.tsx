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

import {PublicLinkButton} from './PublicLinkButton';
import {Seo} from './Seo';

export function NotFoundPage() {
  return (
    <>
      <Seo
        title="Page not found - Co-Scientist"
        description="The page you requested does not exist."
        path={window.location.pathname}
        robots="noindex, nofollow"
      />
      <section className="not-found-page">
        <p className="section-label">404</p>
        <h1>Page not found</h1>
        <p>The page you requested does not exist.</p>
        <div className="landing-actions">
          <PublicLinkButton to="/">Return home</PublicLinkButton>
          <PublicLinkButton to="/runs" variant="outline">
            Open the workbench
          </PublicLinkButton>
        </div>
      </section>
    </>
  );
}
