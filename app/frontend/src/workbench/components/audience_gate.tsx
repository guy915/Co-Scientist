import {useEffect, useRef} from 'react';
import {useLocation} from 'react-router-dom';
import {DEFAULT_AUDIENCE, useAudience} from '../audience_context';

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
 * Fires once per mount. The chooser can be dismissed without picking
 * anything, so closing it commits the general audience — the default is
 * recorded explicitly rather than left as an unset value that merely happens
 * to behave like general.
 *
 * @param props.onOpenAffiliation Opens Settings on the Affiliation section.
 * @param props.chooserOpen Whether the Affiliation chooser is currently
 *   showing; its close is what commits the default.
 */
export function AudienceGate({
  onOpenAffiliation,
  chooserOpen,
}: {
  onOpenAffiliation: () => void;
  chooserOpen: boolean;
}) {
  const {audience, setAudience} = useAudience();
  const {pathname} = useLocation();
  const opened = useRef(false);
  const wasOpen = useRef(false);

  useEffect(() => {
    if (opened.current || audience || isPublicRoute(pathname)) return;
    opened.current = true;
    onOpenAffiliation();
  }, [audience, pathname, onOpenAffiliation]);

  useEffect(() => {
    const dismissed = wasOpen.current && !chooserOpen;
    wasOpen.current = chooserOpen;
    if (dismissed && !audience) setAudience(DEFAULT_AUDIENCE);
  }, [chooserOpen, audience, setAudience]);

  return null;
}
