import {ExternalLink} from '@/shared/ui';

export function PrivacyContent() {
  return (
    <>
      <section>
        <h2>Who is responsible</h2>
        <p>
          Open Co-Scientist is operated by Guy Barel, its individual owner in
          the Netherlands, who is the controller of the personal data described
          here. Contact{' '}
          <ExternalLink href="mailto:guy.barel@open-coscientist.com">
            guy.barel@open-coscientist.com
          </ExternalLink>{' '}
          for privacy questions or a data-rights request.
        </p>
      </section>
      <section>
        <h2>What we collect and why</h2>
        <p>
          We store your research goals, chat messages, uploaded document titles
          and extracted text, selected settings, research runs and their
          results. A random ID saved in your browser connects that work to this
          browser. There is currently no email sign-in or password account.
          Clearing this ID can make your saved work inaccessible; it does not
          delete the server copy.
        </p>
        <p>
          We process this information to provide the research service you
          request, on the basis of performing our agreement with you (GDPR
          Article 6(1)(b)). Providing research content is optional, but we need
          a goal to carry out a run. Please submit only material you have the
          right to use.
        </p>
        <p>
          We also process feedback, technical error reports, request metadata
          and usage counters to maintain the service, investigate failures,
          protect private work and prevent abuse. These purposes rely on our
          legitimate interests in operating a secure, reliable service (Article
          6(1)(f)). We limit diagnostic content and access. You may object to
          processing based on legitimate interests.
        </p>
        <p>
          BYOK provider keys are saved in this browser and sent to our API when
          you request their use. The API stores encrypted run credentials so
          background work can continue. We do not need your email address to use
          the service, and public completion emails are disabled.
        </p>
      </section>
      <section>
        <h2>Models and external sources</h2>
        <p>
          Research goals, chat context and document excerpts are sent to the
          model providers used for your request. The service uses OpenRouter
          free or promotional routes and their upstream hosts, and may use Azure
          OpenAI when available. With BYOK, your selected provider (Anthropic,
          DeepSeek, Gemini, OpenAI or OpenRouter) receives the request and its
          key. A custom model follows that provider’s terms.
        </p>
        <p>
          Free routes may retain prompts or use them for training. Most free
          route profiles do not establish zero retention. The pinned Qwen 3.8
          27B route requests ModelRun only, zero data retention and no data
          collection; that restriction is not a promise about every route or
          fallback. Do not submit confidential material, personal data, medical
          records or credentials in goals, chats or documents.
        </p>
        <p>
          Literature searches send queries derived from your text to PubMed and
          PMC (NCBI), OpenAlex, Europe PMC, arXiv and OpenCitations. Biomedical
          lookups may use ChEMBL, UniProt, STRING, Reactome, Open Targets,
          Ensembl, gnomAD, GWAS Catalog and ClinicalTrials.gov. Web search may
          use Brave or Tavily; opening a source contacts its publisher or
          website. Available scientific database tools may make further lookups.
          A derived query can include words you supplied. These services apply
          their own privacy and retention policies.
        </p>
      </section>
      <section>
        <h2>Hosting, diagnostics and international transfers</h2>
        <p>
          Cloudflare serves the website and, when configured, stores private R2
          database backups. Railway hosts our API, database and literature
          server. Hosting providers receive connection metadata such as IP
          addresses. Sentry receives technical error reports when enabled; the
          configured tracing service receives request, task and model timing and
          usage metadata. The current tracing destination reported by the owner
          is Honeycomb EU. Diagnostics must exclude research text, document
          text, email addresses and provider keys.
        </p>
        <p>
          Hosting and diagnostic providers act as processors for their
          contracted services; model and research services may also process data
          for their own purposes under their terms. We do not sell your data or
          use it for advertising.
        </p>
        <p>
          Some recipients and their infrastructure are outside the European
          Economic Area. Azure’s resource is in Sweden Central, but its Global
          Standard deployment does not guarantee that inference stays in the EU.
          A European resource or tracing region does not establish where every
          provider or subprocessor operates. Where required, transfers need an
          applicable adequacy decision or appropriate safeguards such as the
          European Commission’s standard contractual clauses. Contact the owner
          for the applicable arrangements and a copy of safeguards. Choosing a
          model is not a waiver of your GDPR rights or consent to unspecified
          transfers.
        </p>
      </section>
      <section>
        <h2>How long information stays</h2>
        <p>
          Launch policy keeps saved runs until you delete them: a run-retention
          setting of zero disables automatic run expiry. Draft runs have a
          seven-day expiry policy. Staged uploaded documents have a 30-day
          expiry policy. Currently, text already copied into a run, its results
          or chat remains with that work; deleting only a staged upload does not
          remove those copies. The service checks time-based retention hourly.
        </p>
        <p>
          Standalone chats remain until deleted. Stored run credentials remain
          until their run is deleted; browser keys and preferences remain until
          you remove them. Feedback is limited to 30 days, the newest 200
          submissions and 10 MiB. Local diagnostic logs have row limits rather
          than a fixed expiry time. Spent abuse allowances survive deletion
          under a seven-day expiry policy; expired counters and detached
          receipts are cleaned hourly in bounded batches. A saved run's
          host-admission mapping remains with that run. Hashed erasure markers
          stay for 24 hours to block late background writes from recreating
          deleted work.
        </p>
        <p>
          A separate operator funding ledger keeps numeric charge, usage and
          receipt records without an automatic expiry to enforce the total
          spending cap. It stores no research text, provider keys or browser
          ownership ID. Your export includes receipts linked to your current
          admission records; deletion removes that ownership link without
          refunding spent money.
        </p>
        <p>
          Deletion from the live service does not instantly remove older
          database backups or copies held by external recipients. R2 backups
          have a 30-day object-expiry policy. Cloudflare normally removes
          expired objects within 24 hours, with possible delays. If we restore
          a backup, we must reapply erasure decisions before serving that work.
          Deleting our copy does not erase prompts a model provider has already
          received.
        </p>
        <p>
          Sentry’s free Developer plan provides a{' '}
          <ExternalLink href="https://sentry.io/pricing/">
            30-day lookback
          </ExternalLink>
          . Honeycomb retains trace events for{' '}
          <ExternalLink href="https://docs.honeycomb.io/get-started/manage-costs/how-honeycomb-calculates-usage/">
            60 days from ingestion
          </ExternalLink>
          .{' '}
          <ExternalLink href="https://docs.railway.com/observability/logs">
            Railway’s application log history
          </ExternalLink>{' '}
          is seven days on Hobby or 30 days on Pro; upgrading can make older
          history visible again. When enabled,{' '}
          <ExternalLink href="https://developers.cloudflare.com/workers/observability/logs/workers-logs/">
            Cloudflare Workers Logs
          </ExternalLink>{' '}
          retain logs for three days on Free or seven days on Paid. These
          plan-dependent application-log windows do not establish when every
          infrastructure or security record is erased. Contact the owner for
          the applicable hosting plan and other provider-held records.
        </p>
      </section>
      <section>
        <h2>Your rights</h2>
        <p>
          Open Settings → Data in this browser to export your runs, chats,
          extracted documents and settings as a JSON ZIP, or to delete all work
          belonging to this browser identity. The export excludes provider keys
          and original uploaded file bytes, which we do not store. Deletion
          removes stored run credentials and documents and clears the
          application’s browser storage. Keep the ownership ID until you finish:
          clearing browser storage alone does not delete server data.
        </p>
        <p>
          You may request access, correction, erasure, restriction of processing
          and, where applicable, a portable copy of your data. You may object to
          processing based on legitimate interests. If we rely on consent for a
          purpose, you can withdraw it without changing the lawfulness of
          earlier processing. Contact the owner using the address above; we
          normally respond within one month and will explain any lawful
          extension or limitation.
        </p>
        <p>
          We may need proportionate evidence that the data is yours. Please do
          not email your provider keys or the browser’s ownership ID. You can
          complain to the Dutch supervisory authority, the{' '}
          <ExternalLink href="https://autoriteitpersoonsgegevens.nl/en">
            Autoriteit Persoonsgegevens
          </ExternalLink>
          , or your local supervisory authority.
        </p>
      </section>
      <section>
        <h2>Cookies and browser storage</h2>
        <p>
          The application sets no first-party cookies. It uses browser storage
          for your ownership ID, chosen appearance, BYOK keys and models,
          session view, diagnostic session anchor and safe retry/reload
          recovery. These support the functionality you request; there are no
          application advertising or analytics storage keys.
        </p>
        <p>
          The trailer is a link to YouTube. We load no embedded video or Google
          resources: YouTube receives a request only when you open that link,
          and its own privacy and storage policies then apply. All application
          storage serves the necessary functions listed here, so the application
          does not need a cookie-consent banner.
        </p>
        <p>
          Local storage keys are co_scientist_client_id, cosci-theme,
          cosci-api-keys, the migrated legacy cosci-api-key, cosci-api-provider,
          cosci-api-model, cosci-api-supervisor-model, cosci-api-custom-models,
          cosci:session-side, cosci:session-side:&lt;runId&gt; and
          cosci:session-tab:&lt;runId&gt;. Session storage keys are
          cosci-logs-session-baseline, co_scientist_log_pause_until (temporary
          diagnostic rate-limit recovery),
          co_scientist_pending_run_create:&lt;chatId&gt; and
          coscientist:chunk-reload-at. Local values last until cleared; session
          values normally end when the tab closes.
        </p>
      </section>
    </>
  );
}
