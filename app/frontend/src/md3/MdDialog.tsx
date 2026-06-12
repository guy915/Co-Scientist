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

import "@material/web/dialog/dialog.js";
import "@material/web/button/text-button.js";
import type { MdDialog as MdDialogElement } from "@material/web/dialog/dialog.js";
import { useEffect, useRef } from "react";

interface MdDialogProps {
  open: boolean;
  onClose: () => void;
  headline?: React.ReactNode;
  children: React.ReactNode;
  actions?: React.ReactNode;
}

export function MdDialog({ open, onClose, headline, children, actions }: MdDialogProps) {
  const ref = useRef<MdDialogElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const handler = () => onClose();
    el.addEventListener("close", handler);
    return () => el.removeEventListener("close", handler);
  }, [onClose]);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (open) el.show();
    else if (el.open) void el.close();
  }, [open]);

  return (
    <md-dialog ref={ref as React.Ref<MdDialogElement>}>
      {headline && <div slot="headline">{headline}</div>}
      <div slot="content">{children}</div>
      {actions && <div slot="actions">{actions}</div>}
    </md-dialog>
  );
}
