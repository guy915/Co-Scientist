import {useEffect, useRef} from 'react';
import {useLocation} from 'react-router-dom';
import {useAudience} from '../audience_context';

// Routes reachable by people outside the workspace: a shared report link and
// the researcher access page. Asking a visitor there to declare an
// affiliation before they can read what was shared with them makes no sense,
// so the gate stays shut on these.
const PUBLIC_PREFIXES: readonly string[] = ['/shared/', '/access'];

function isPublicRoute(pathname: string): boolean {
  return PUBLIC_PREFIXES.some(prefix => pathname.startsWith(prefix));
}

/**
 * First-visit gate. Renders nothing itself: when no audience has been chosen
 * it opens the Settings dialog on its Affiliation section, so the chooser is
 * the same surface used to change the answer later.
 *
 * Fires once per mount. Closing the dialog without choosing leaves the
 * audience unset, which behaves as the general audience, and the gate does
 * not reopen until the next load.
 *
 * @param props.onOpenAffiliation Opens Settings on the Affiliation section.
 */
export function AudienceGate({
  onOpenAffiliation,
}: {
  onOpenAffiliation: () => void;
}) {
  const {audience} = useAudience();
  const {pathname} = useLocation();
  const opened = useRef(false);

  useEffect(() => {
    if (opened.current || audience || isPublicRoute(pathname)) return;
    opened.current = true;
    onOpenAffiliation();
  }, [audience, pathname, onOpenAffiliation]);

  return null;
}
