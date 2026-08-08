import {useEffect, useRef} from 'react';
import {useAudience} from '../audience_context';

/**
 * First-visit gate. Renders nothing itself: while no audience has been chosen
 * it opens the ordinary Settings dialog on its Affiliation section, so the
 * chooser is the same surface — header, section rail and all — used to change
 * the answer later.
 *
 * The question is asked once per page load, on every route, and it is asked
 * as an ordinary dialog: it can be closed, Escaped, or navigated away from
 * via the section rail. Leaving it unanswered commits nothing (see
 * AudienceProvider, which has no default), so an unset audience reads as the
 * plain general workspace and the question comes back on the next load.
 *
 * Asking only once per load is what makes that possible: `asked` marks the
 * question as put, so closing the dialog — or switching to another Settings
 * section, which likewise leaves the Affiliation section — is not fought by
 * the gate re-opening it underneath the user.
 *
 * Answering dismisses it: the gate closes the chooser it opened, so picking
 * an option returns the user to the page they asked for rather than leaving
 * Settings sitting over it.
 *
 * @param props.onOpenAffiliation Opens Settings on the Affiliation section.
 * @param props.onCloseChooser Closes the Settings dialog again.
 * @param props.chooserOpen Whether the Affiliation chooser is currently
 *   showing.
 */
export function AudienceGate({
  onOpenAffiliation,
  onCloseChooser,
  chooserOpen,
}: {
  onOpenAffiliation: () => void;
  onCloseChooser: () => void;
  chooserOpen: boolean;
}) {
  const {audience} = useAudience();
  // Whether the question has been put at all this page load; see above. A
  // chooser already open at mount counts as having put it.
  const asked = useRef(chooserOpen);
  // Only a chooser this gate opened is auto-closed on an answer -- a Settings
  // dialog the user opened themselves is theirs to close. Ownership ends when
  // that chooser closes (see the release effect), so a later self-opened
  // Settings dialog is not torn down by a change of affiliation made in it.
  const owned = useRef(false);

  useEffect(() => {
    if (audience || chooserOpen || asked.current) return;
    asked.current = true;
    owned.current = true;
    onOpenAffiliation();
  }, [audience, chooserOpen, onOpenAffiliation]);

  // Release ownership once the chooser has actually opened and closed again.
  // Keyed on the open->closed transition rather than on `chooserOpen` being
  // false, which is also its state in the commit where the effect above has
  // only just asked for it to open.
  const wasOpen = useRef(false);
  useEffect(() => {
    if (chooserOpen) wasOpen.current = true;
    else if (wasOpen.current) {
      wasOpen.current = false;
      owned.current = false;
    }
  }, [chooserOpen]);

  useEffect(() => {
    if (!audience || !owned.current) return;
    owned.current = false;
    onCloseChooser();
  }, [audience, onCloseChooser]);

  return null;
}
