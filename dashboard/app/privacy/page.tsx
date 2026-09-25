import type { Metadata } from "next";
import Link from "next/link";
import {
  CONTACT_EMAIL,
  LegalCard,
  LegalH2,
  LegalList,
  LegalP,
  PublicShell,
  ScopeCode,
} from "@/components/public";

export const metadata: Metadata = {
  title: "Privacy Policy — LETAN Media Sync",
  description:
    "Privacy Policy for LETAN Media Sync: how Google OAuth and YouTube data are used, stored, and protected.",
};

export default function PrivacyPage() {
  return (
    <PublicShell>
      <p className="text-[11px] font-bold uppercase tracking-[0.12em] text-indigo-600">
        Legal
      </p>
      <h1 className="mt-0.5 text-xl font-extrabold tracking-tight text-slate-900 sm:text-2xl">
        Privacy Policy — LETAN Media Sync
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
          <LegalH2>1. What LETAN Media Sync does</LegalH2>
          <LegalP>
            LETAN Media Sync is a video publishing and YouTube channel management
            tool. It helps channel operators publish videos, manage channel
            content, and manage comments on the YouTube channels they operate —
            including AI-assisted metadata and AI-assisted comment replies that
            the operator configures and controls.
          </LegalP>
        </div>

        <div>
          <LegalH2>2. Google OAuth: you connect your own channel</LegalH2>
          <LegalP>
            The app uses Google OAuth so that you can connect your own YouTube
            channel yourself. The app only ever accesses the channels that you
            explicitly authorize through the Google OAuth consent screen. It
            never accesses channels you have not granted access to, and it never
            asks for your Google password.
          </LegalP>
        </div>

        <div>
          <LegalH2>3. Scopes we request and why</LegalH2>
          <LegalP>
            We request only the YouTube scopes the app&apos;s features need:
          </LegalP>
          <LegalList
            items={[
              <>
                <ScopeCode>youtube.readonly</ScopeCode> — to read channel, video,
                and comment information (for example, listing your videos,
                checking publish status, and reading comments on your videos).
              </>,
              <>
                <ScopeCode>youtube.upload</ScopeCode> — to upload videos to your
                connected channel when you request it or when your configured
                publishing schedule triggers an upload you set up.
              </>,
              <>
                <ScopeCode>youtube.force-ssl</ScopeCode> — to read comments on
                your videos, generate AI draft replies, and post replies to your
                viewers when you enable and approve the comment-reply feature.
              </>,
            ]}
          />
        </div>

        <div>
          <LegalH2>4. How your Google / YouTube data is used</LegalH2>
          <LegalP>Data received from Google APIs is used only to operate the features you configure:</LegalP>
          <LegalList
            items={[
              "Reading channel, video, and comment data to display your channel workspace (videos, publish status, and comments).",
              "Uploading videos to your channel per your request or your publishing configuration (schedule, limits, and metadata you set).",
              "Reading comments on your videos so you can review and manage them.",
              "Creating AI draft replies to comments, using a dedicated comment-reply prompt that is fully separate from the prompt used for video metadata (titles, descriptions, hashtags).",
              "Posting a reply to YouTube only when you enable the reply feature and under the mode and limits you configure (manual review or automatic posting with daily limits and approval rules you control).",
            ]}
          />
        </div>

        <div>
          <LegalH2>5. How credentials and data are stored and protected</LegalH2>
          <LegalList
            items={[
              "To keep your channel connected, our backend stores the OAuth access and refresh credentials for each channel you connect. They are kept in access-controlled server-side storage.",
              "Credentials and API secrets are never displayed in the app interface and are never exposed to the browser. The web dashboard communicates with YouTube exclusively through our backend; sign-in to the dashboard itself uses a separate short-lived session cookie.",
              "Only the channel workspaces you authorized are accessed with these credentials — one channel's credentials are never used to act on another channel.",
            ]}
          />
        </div>

        <div>
          <LegalH2>6. What we never do with your data</LegalH2>
          <LegalList
            items={[
              "We do not sell your personal data.",
              "We do not sell Google or YouTube data.",
              "We do not use data obtained from Google APIs for advertising purposes.",
              "We do not share data obtained from Google APIs with third parties, except with the service processors strictly necessary to run the app's features: the YouTube Data API itself, and the AI text-generation service that receives comment text and video metadata solely to produce the draft replies and metadata you request. These processors receive only the minimum data needed for that purpose.",
            ]}
          />
        </div>

        <div>
          <LegalH2>7. Disconnecting and deleting your data</LegalH2>
          <LegalList
            items={[
              "You can disconnect a YouTube channel at any time by removing the channel destination in the app, which deletes the stored OAuth credentials for that channel so no further API calls are made on its behalf.",
              "You can also revoke the app's access at any time from your Google Account permissions page (myaccount.google.com/permissions). Revoking stops all future access immediately.",
              "You can request deletion of data associated with your account or channel (connected-channel records, stored comments, generated drafts, and credentials) by emailing us. We will confirm once the deletion is complete.",
            ]}
          />
          <LegalP>
            To request deletion, email{" "}
            <a
              href={`mailto:${CONTACT_EMAIL}`}
              className="font-semibold text-indigo-600 hover:underline"
            >
              {CONTACT_EMAIL}
            </a>{" "}
            from an address associated with your channel and include the channel
            name or URL.
          </LegalP>
        </div>

        <div>
          <LegalH2>8. Google API Services User Data Policy &amp; Limited Use</LegalH2>
          <LegalP>
            Our use of information received from Google APIs complies with the{" "}
            <span className="font-semibold text-slate-800">
              Google API Services User Data Policy
            </span>
            , including its Limited Use requirements. Specifically:
          </LegalP>
          <LegalList
            items={[
              "We request access only to the scopes needed for the user-facing features described above, and we use the data only for those features.",
              "We do not transfer Google user data to any other party except as necessary to provide those features (the YouTube Data API and the AI drafting service described in section 6), and we prohibit those processors from using the data for any independent purpose.",
              "We do not use Google user data to build advertising profiles, to serve advertising, or to train general-purpose machine-learning models unrelated to the features you use.",
              "Human access to Google user data is limited to operating, securing, and supporting the service (for example, investigating an upload or reply failure you report).",
            ]}
          />
        </div>

        <div>
          <LegalH2>9. Contact</LegalH2>
          <LegalP>
            For any privacy question, access request, or deletion request,
            contact us at{" "}
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
            href="/terms"
            className="inline-flex min-h-[44px] items-center justify-center gap-1.5 rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700 shadow-sm transition hover:border-slate-300 hover:bg-slate-50 sm:min-h-[38px]"
          >
            Terms of Service
          </Link>
        </div>
      </LegalCard>
    </PublicShell>
  );
}
