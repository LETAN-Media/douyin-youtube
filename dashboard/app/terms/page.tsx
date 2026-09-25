import type { Metadata } from "next";
import Link from "next/link";
import {
  CONTACT_EMAIL,
  LegalCard,
  LegalH2,
  LegalList,
  LegalP,
  PublicShell,
} from "@/components/public";

export const metadata: Metadata = {
  title: "Terms of Service — LETAN Media Sync",
  description:
    "Terms of Service for LETAN Media Sync: acceptable use, publishing responsibility, AI features, and service limits.",
};

export default function TermsPage() {
  return (
    <PublicShell>
      <p className="text-[11px] font-bold uppercase tracking-[0.12em] text-indigo-600">
        Legal
      </p>
      <h1 className="mt-0.5 text-xl font-extrabold tracking-tight text-slate-900 sm:text-2xl">
        Terms of Service — LETAN Media Sync
      </h1>
      <p className="mt-1 text-sm text-slate-500">
        Last updated: September 25, 2026 · Contact:{" "}
        <a
          href={`mailto:${CONTACT_EMAIL}`}
          className="font-semibold text-indigo-600 hover:underline"
        >
          {CONTACT_EMAIL}
        </a>
      </p>

      <LegalCard>
        <div>
          <LegalH2>1. What the service provides</LegalH2>
          <LegalP>
            LETAN Media Sync provides video publishing, YouTube channel
            management, and comment management for channels you operate. You
            connect your YouTube channel via Google OAuth, configure publishing
            schedules and limits, and optionally enable AI-assisted video
            metadata and AI-assisted comment replies.
          </LegalP>
        </div>

        <div>
          <LegalH2>2. Connect only accounts you are authorized to manage</LegalH2>
          <LegalP>
            You may only connect Google accounts and YouTube channels that you
            own or that you are explicitly authorized to manage. You must not
            connect third-party channels without the channel owner&apos;s
            permission, and you must disconnect any channel promptly if your
            authorization ends.
          </LegalP>
        </div>

        <div>
          <LegalH2>3. You are responsible for content you publish</LegalH2>
          <LegalList
            items={[
              "You are solely responsible for every video, title, description, tag, comment reply, and other content the service uploads or posts on your behalf.",
              "You must ensure your content does not infringe copyrights, trademarks, or other rights, and that you hold all rights needed to publish it (including rights to any reused or third-party source material).",
              "You must not use the service to send spam, harass or abuse viewers, mislead audiences, or violate YouTube's Terms of Service, Community Guidelines, or API Services Terms of Service.",
            ]}
          />
        </div>

        <div>
          <LegalH2>4. AI-generated metadata and replies need your review</LegalH2>
          <LegalList
            items={[
              "AI-generated titles, descriptions, hashtags, and comment replies are suggestions produced from your configuration and may contain errors. Review them before they are published whenever your workflow allows it.",
              "Comment Auto Reply is an optional feature. When enabled, you are responsible for the reply mode you choose, the daily limits and intervals you configure, the reply prompt and style you set, and every reply the service posts under your configuration.",
              "The service classifies comments and withholds replies from spam, abuse, and sensitive content by design, but automated classification is not perfect — monitor your channel and disable automatic posting if replies do not meet your standards.",
            ]}
          />
        </div>

        <div>
          <LegalH2>5. Service availability, quotas, and limits</LegalH2>
          <LegalList
            items={[
              "The service depends on external providers — the YouTube Data API, Google OAuth, the Douyin creator-feed provider (RapidAPI), and the AI text-generation service — and may be interrupted, delayed, or degraded when any of them is unavailable or changes its behavior.",
              "API quotas and rate limits (including YouTube API quota and feed-provider request quotas) may delay or prevent uploads, imports, comment scans, or replies. Daily upload limits and scheduling slots you configure also bound what the service will do.",
              "To stay compliant with platform policies (including YouTube and Google API policies), we may change, limit, or disable features at any time — for example, pausing uploads or replies when credentials are revoked, scopes are missing, or policy requires it.",
            ]}
          />
        </div>

        <div>
          <LegalH2>6. Acceptable use</LegalH2>
          <LegalList
            items={[
              "Do not use the service for spam, artificial engagement, misleading metadata, mass unsolicited replies, or any abusive behavior.",
              "Do not upload content that infringes intellectual-property rights or violates applicable law.",
              "Do not attempt to circumvent quotas, access controls, or the authorization boundaries between channel workspaces.",
              "Do not misrepresent AI-generated replies as human review where such disclosure is required by platform policy or law.",
            ]}
          />
        </div>

        <div>
          <LegalH2>7. Disconnecting and data</LegalH2>
          <LegalP>
            You may disconnect a channel at any time by removing its destination
            in the app (which deletes its stored OAuth credentials) or by
            revoking access in your Google Account. How we handle Google user
            data — including deletion requests — is described in our{" "}
            <Link href="/privacy" className="font-semibold text-indigo-600 hover:underline">
              Privacy Policy
            </Link>
            .
          </LegalP>
        </div>

        <div>
          <LegalH2>8. Disclaimer</LegalH2>
          <LegalP>
            The service is provided &ldquo;as is&rdquo; and &ldquo;as
            available&rdquo;, without warranties of any kind, whether express or
            implied, including warranties of uninterrupted operation, publishing
            reach, monetization outcomes, or fitness for a particular purpose. To
            the maximum extent permitted by law, we are not liable for indirect,
            incidental, or consequential damages arising from your use of the
            service, including content rejected or removed by YouTube or actions
            taken by external providers.
          </LegalP>
        </div>

        <div>
          <LegalH2>9. Changes to these terms</LegalH2>
          <LegalP>
            We may update these terms to reflect feature or policy changes. The
            current version is always published at this URL, and continued use
            of the service after an update constitutes acceptance of the updated
            terms.
          </LegalP>
        </div>

        <div>
          <LegalH2>10. Contact</LegalH2>
          <LegalP>
            Questions about these terms:{" "}
            <a
              href={`mailto:${CONTACT_EMAIL}`}
              className="font-semibold text-indigo-600 hover:underline"
            >
              {CONTACT_EMAIL}
            </a>
            .
          </LegalP>
        </div>

        <div className="mt-8 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-5">
          <Link
            href="/"
            className="inline-flex min-h-[44px] items-center justify-center gap-1.5 rounded-xl bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-[0_1px_2px_rgba(79,70,229,0.4)] transition hover:bg-indigo-500 sm:min-h-[38px]"
          >
            ← Back to home
          </Link>
          <Link
            href="/privacy"
            className="inline-flex min-h-[44px] items-center justify-center gap-1.5 rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700 shadow-sm transition hover:border-slate-300 hover:bg-slate-50 sm:min-h-[38px]"
          >
            Privacy Policy
          </Link>
        </div>
      </LegalCard>
    </PublicShell>
  );
}
