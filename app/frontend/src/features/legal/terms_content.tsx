import {ExternalLink} from '@/shared/ui';

export function TermsContent() {
  return (
    <>
      <section>
        <h2>A research aid</h2>
        <p>
          Co-Scientist helps you explore, evaluate and compare research
          hypotheses. Results can be incomplete, incorrect or unsupported;
          citations and safety checks can fail. Verify claims, sources and
          experimental proposals independently before relying on them.
        </p>
        <p>
          The service does not provide medical, safety, legal or other
          professional advice. It does not approve clinical decisions or
          experiments. Obtain qualified advice and any required ethical,
          institutional or regulatory approval.
        </p>
      </section>
      <section>
        <h2>Acceptable use</h2>
        <p>
          Use the service lawfully and respect other people’s rights. Do not
          request operational help for biological or chemical weapons, dangerous
          pathogen enhancement, explosives, poisoning, cyber intrusion or other
          harmful activity. Do not evade safety holds, abuse usage limits, probe
          another person’s private work or disrupt the service. Safety screening
          can hold, block or exclude content; it is not proof that everything
          else is safe.
        </p>
        <p>
          Submit only content you are entitled to process and share with the
          selected providers. Do not submit confidential or personal data,
          medical records or secrets in research content. Some free model routes
          may retain prompts or use them for training. External source and model
          terms also apply to their services.
        </p>
      </section>
      <section>
        <h2>Your work and provider keys</h2>
        <p>
          You retain the rights you have in your submissions. You allow the
          processing needed to provide your requested research, including
          sending relevant content to model providers and search services. We do
          not promise that generated material is original or that you receive
          exclusive rights to it. Check third-party rights and source licences
          before publishing or reusing results.
        </p>
        <p>
          With BYOK, you choose and remain responsible for your provider
          account, key permissions, charges, quotas and provider terms. Saved
          keys are available to this browser and encrypted credentials may be
          retained for background runs. Revoke a compromised key with its
          provider; removing it here cannot revoke it there.
        </p>
        <p>
          Saved work currently belongs to a random ID in this browser, not an
          authenticated account. Protect your browser and device. Clearing
          browser storage can remove access to saved work without deleting it
          from the server.
        </p>
      </section>
      <section>
        <h2>Availability and responsibility</h2>
        <p>
          The service is provided as available, without a promise of accuracy,
          fitness for a particular purpose, uninterrupted operation or
          preservation of every result. Models, features and free capacity may
          change or become unavailable. Keep a copy of work you need. We may
          restrict abusive use or stop unsafe requests.
        </p>
        <p>
          To the extent permitted by applicable law, there is no warranty and
          the owner is not responsible for losses caused by relying on research
          output. These terms do not exclude mandatory consumer rights,
          liability that cannot lawfully be excluded or your data protection
          rights.
        </p>
      </section>
      <section>
        <h2>Contact and changes</h2>
        <p>
          The service is operated by Guy Barel, its individual owner in the
          Netherlands. Contact{' '}
          <ExternalLink href="mailto:guy.barel@open-coscientist.com">
            guy.barel@open-coscientist.com
          </ExternalLink>{' '}
          with questions. We will identify material changes here. Dutch law
          applies subject to any mandatory protections that apply to you.
        </p>
      </section>
    </>
  );
}
