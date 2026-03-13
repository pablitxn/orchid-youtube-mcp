import { type FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import {
  downloadYouTubeAudio,
  getYouTubeAuthStatus,
  type AudioDownloadPreset,
  type YouTubeAuthMode,
  type YouTubeAuthStatus,
} from "../api";
import {
  formatDateTime,
  formatYouTubeAuthMode,
  youtubeAuthTone,
} from "../format";

const presetOptions: Array<{
  value: AudioDownloadPreset;
  label: string;
  description: string;
}> = [
  {
    value: "mp3_192",
    label: "MP3 192 kbps",
    description: "Balanced default for downloads you want to keep handy.",
  },
  {
    value: "mp3_128",
    label: "MP3 128 kbps",
    description: "Smaller file size when you only need the spoken content quickly.",
  },
  {
    value: "m4a_128",
    label: "M4A 128 kbps",
    description: "AAC/M4A output with broad device support and smaller files.",
  },
  {
    value: "opus_160",
    label: "Opus 160 kbps",
    description: "Higher-efficiency codec if your player handles Opus well.",
  },
];

export function AudioDownloadView() {
  const [youtubeUrl, setYoutubeUrl] = useState("");
  const [preset, setPreset] = useState<AudioDownloadPreset>("mp3_192");
  const [authStatus, setAuthStatus] = useState<YouTubeAuthStatus | null>(null);
  const [authError, setAuthError] = useState<string | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [downloadState, setDownloadState] = useState<"idle" | "downloading">("idle");
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [downloadResult, setDownloadResult] = useState<{
    filename: string | null;
    authMode: YouTubeAuthMode | null;
    requestedAt: string;
  } | null>(null);

  useEffect(() => {
    const controller = new AbortController();

    async function loadAuthStatus() {
      setAuthLoading(true);
      setAuthError(null);

      try {
        const nextStatus = await getYouTubeAuthStatus();
        if (!controller.signal.aborted) {
          setAuthStatus(nextStatus);
        }
      } catch (failure) {
        if (!controller.signal.aborted) {
          setAuthError(
            failure instanceof Error
              ? failure.message
              : "Could not load the current YouTube auth state.",
          );
        }
      } finally {
        if (!controller.signal.aborted) {
          setAuthLoading(false);
        }
      }
    }

    void loadAuthStatus();

    return () => controller.abort();
  }, []);

  const selectedPreset =
    presetOptions.find((option) => option.value === preset) ?? presetOptions[0];
  const effectiveAuthMode = downloadResult?.authMode ?? authStatus?.mode ?? "none";

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setDownloadState("downloading");
    setDownloadError(null);

    try {
      const result = await downloadYouTubeAudio({
        youtube_url: youtubeUrl.trim(),
        preset,
      });
      setDownloadResult({
        filename: result.filename,
        authMode: result.authMode,
        requestedAt: new Date().toISOString(),
      });
    } catch (failure) {
      setDownloadError(
        failure instanceof Error
          ? failure.message
          : "Could not download the requested audio.",
      );
    } finally {
      setDownloadState("idle");
    }
  }

  return (
    <section className="page-stack">
      <section className="panel hero compact">
        <div>
          <p className="eyebrow">Ephemeral download</p>
          <h1>Grab audio-only straight from the browser.</h1>
          <p className="hero-copy">
            This uses the same managed <code>yt-dlp</code> credentials, returns the
            audio as a browser download, and removes the temporary server-side file
            right after the response finishes.
          </p>
        </div>

        <div className="toolbar-actions">
          <Link to="/" className="button secondary">
            Back to library
          </Link>
          <Link to="/" className="button secondary">
            Manage cookies
          </Link>
        </div>
      </section>

      <div className="content-grid">
        <section className="panel form-panel">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Audio download</p>
              <h2>Request one-off audio</h2>
            </div>
            <span className="mono-tag">POST /v1/admin/youtube-auth/download-audio</span>
          </div>

          <p className="panel-copy">
            Nothing gets indexed, copied into object storage, or attached to a saved
            video entry. This is just a credential-backed browser download path.
          </p>

          <form className="auth-form" onSubmit={handleSubmit}>
            <label className="field">
              <span>YouTube URL</span>
              <input
                required
                type="url"
                placeholder="https://www.youtube.com/watch?v=..."
                value={youtubeUrl}
                onChange={(event) => setYoutubeUrl(event.target.value)}
              />
            </label>

            <label className="field">
              <span>Output preset</span>
              <select
                value={preset}
                onChange={(event) =>
                  setPreset(event.target.value as AudioDownloadPreset)
                }
              >
                {presetOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>

            <p className="helper-copy">{selectedPreset.description}</p>

            {downloadError !== null ? (
              <p className="inline-error">{downloadError}</p>
            ) : null}

            <div className="toolbar-actions">
              <button
                type="submit"
                className="button primary"
                disabled={
                  downloadState !== "idle" || youtubeUrl.trim().length === 0
                }
              >
                {downloadState === "downloading"
                  ? "Preparing download…"
                  : "Download audio"}
              </button>
              <button
                type="button"
                className="button secondary"
                disabled={downloadState !== "idle" || youtubeUrl.length === 0}
                onClick={() => {
                  setYoutubeUrl("");
                  setDownloadError(null);
                }}
              >
                Clear
              </button>
            </div>
          </form>

          {downloadResult !== null ? (
            <div className="state-message">
              <div className="pill-row">
                <span className={`status-pill ${youtubeAuthTone(effectiveAuthMode)}`}>
                  {formatYouTubeAuthMode(effectiveAuthMode)}
                </span>
                {downloadResult.filename !== null ? (
                  <span className="mono-tag">{downloadResult.filename}</span>
                ) : null}
              </div>
              <p className="helper-copy">
                The browser download was triggered at{" "}
                {formatDateTime(downloadResult.requestedAt)}.
              </p>
            </div>
          ) : null}
        </section>

        <section className="panel auth-panel">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Credential state</p>
              <h2>Managed cookie snapshot</h2>
            </div>
            <span className={`status-pill ${youtubeAuthTone(authStatus?.mode ?? "none")}`}>
              {formatYouTubeAuthMode(authStatus?.mode ?? "none")}
            </span>
          </div>

          <p className="panel-copy">
            Public videos may still download anonymously, but this page is mainly
            here to exploit the managed authenticated path when YouTube starts
            gating access.
          </p>

          {authLoading ? <p className="state-message">Loading auth snapshot…</p> : null}
          {authError !== null ? <p className="inline-error">{authError}</p> : null}

          {authStatus !== null ? (
            <dl className="meta-grid">
              <div>
                <dt>Mode</dt>
                <dd>{formatYouTubeAuthMode(authStatus.mode)}</dd>
              </div>
              <div>
                <dt>Source</dt>
                <dd>{authStatus.source_label ?? "n/a"}</dd>
              </div>
              <div>
                <dt>Updated</dt>
                <dd>{formatDateTime(authStatus.updated_at)}</dd>
              </div>
              <div>
                <dt>Runtime file</dt>
                <dd>{authStatus.runtime_file_present ? "present" : "absent"}</dd>
              </div>
              <div>
                <dt>YouTube domains</dt>
                <dd>{authStatus.contains_youtube_domains ? "yes" : "no"}</dd>
              </div>
              <div>
                <dt>Login cookies</dt>
                <dd>{authStatus.has_login_cookie_names ? "detected" : "not detected"}</dd>
              </div>
            </dl>
          ) : null}
        </section>
      </div>
    </section>
  );
}
