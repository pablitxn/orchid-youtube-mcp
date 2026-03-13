import { type FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import {
  createSavedAudioDownload,
  deleteSavedAudioDownload,
  getSavedAudioDownloadUrl,
  getYouTubeAuthStatus,
  listSavedAudioDownloads,
  type AudioDownloadPreset,
  type SavedAudioDownload,
  type YouTubeAuthStatus,
} from "../api";
import {
  formatBytes,
  formatDateTime,
  formatDuration,
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
    description: "Smaller file size when you mainly care about the spoken content.",
  },
  {
    value: "m4a_128",
    label: "M4A 128 kbps",
    description: "AAC/M4A output with broad device support and compact files.",
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
  const [downloads, setDownloads] = useState<SavedAudioDownload[]>([]);
  const [downloadsLoading, setDownloadsLoading] = useState(true);
  const [downloadsError, setDownloadsError] = useState<string | null>(null);
  const [createState, setCreateState] = useState<"idle" | "creating">("idle");
  const [createError, setCreateError] = useState<string | null>(null);
  const [latestSaved, setLatestSaved] = useState<SavedAudioDownload | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();

    async function loadPageData() {
      setAuthLoading(true);
      setDownloadsLoading(true);
      setAuthError(null);
      setDownloadsError(null);

      try {
        const [nextAuthStatus, nextDownloads] = await Promise.all([
          getYouTubeAuthStatus(),
          listSavedAudioDownloads(),
        ]);

        if (controller.signal.aborted) {
          return;
        }

        setAuthStatus(nextAuthStatus);
        setDownloads(nextDownloads.downloads);
      } catch (failure) {
        if (controller.signal.aborted) {
          return;
        }

        const message =
          failure instanceof Error
            ? failure.message
            : "Could not load the audio download subapp.";
        setAuthError(message);
        setDownloadsError(message);
      } finally {
        if (!controller.signal.aborted) {
          setAuthLoading(false);
          setDownloadsLoading(false);
        }
      }
    }

    void loadPageData();

    return () => controller.abort();
  }, []);

  const selectedPreset =
    presetOptions.find((option) => option.value === preset) ?? presetOptions[0];

  async function refreshDownloads() {
    setDownloadsLoading(true);
    setDownloadsError(null);

    try {
      const nextDownloads = await listSavedAudioDownloads();
      setDownloads(nextDownloads.downloads);
    } catch (failure) {
      setDownloadsError(
        failure instanceof Error
          ? failure.message
          : "Could not refresh the saved downloads table.",
      );
    } finally {
      setDownloadsLoading(false);
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setCreateState("creating");
    setCreateError(null);

    try {
      const savedDownload = await createSavedAudioDownload({
        youtube_url: youtubeUrl.trim(),
        preset,
      });
      setLatestSaved(savedDownload);
      await refreshDownloads();
    } catch (failure) {
      setCreateError(
        failure instanceof Error
          ? failure.message
          : "Could not save the requested audio download.",
      );
    } finally {
      setCreateState("idle");
    }
  }

  async function handleDelete(download: SavedAudioDownload) {
    if (!window.confirm(`Delete saved audio "${download.filename}"?`)) {
      return;
    }

    setDeletingId(download.id);
    setDownloadsError(null);

    try {
      await deleteSavedAudioDownload(download.id);
      if (latestSaved?.id === download.id) {
        setLatestSaved(null);
      }
      await refreshDownloads();
    } catch (failure) {
      setDownloadsError(
        failure instanceof Error
          ? failure.message
          : "Could not delete the saved audio download.",
      );
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <section className="page-stack">
      <section className="panel hero compact">
        <div>
          <p className="eyebrow">Audio vault</p>
          <h1>Save browser-ready audio downloads in MinIO.</h1>
          <p className="hero-copy">
            This subapp keeps the managed <code>yt-dlp</code> flow, but now stores
            each generated file in object storage so you can come back later and
            download it again without re-running the YouTube fetch.
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
              <p className="eyebrow">Create download</p>
              <h2>Persist a new audio artifact</h2>
            </div>
            <span className="mono-tag">POST /v1/admin/youtube-auth/audio-downloads</span>
          </div>

          <p className="panel-copy">
            The file is downloaded once with the current auth state, uploaded to
            MinIO, and added to the history table below.
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

            {createError !== null ? <p className="inline-error">{createError}</p> : null}

            <div className="toolbar-actions">
              <button
                type="submit"
                className="button primary"
                disabled={createState !== "idle" || youtubeUrl.trim().length === 0}
              >
                {createState === "creating" ? "Saving audio…" : "Save audio"}
              </button>
              <button
                type="button"
                className="button secondary"
                disabled={createState !== "idle" || youtubeUrl.length === 0}
                onClick={() => {
                  setYoutubeUrl("");
                  setCreateError(null);
                }}
              >
                Clear
              </button>
            </div>
          </form>

          {latestSaved !== null ? (
            <div className="state-message">
              <div className="pill-row">
                <span className={`status-pill ${youtubeAuthTone(latestSaved.auth_mode)}`}>
                  {formatYouTubeAuthMode(latestSaved.auth_mode)}
                </span>
                <span className="mono-tag">{latestSaved.filename}</span>
              </div>

              <p className="helper-copy">
                Saved at {formatDateTime(latestSaved.created_at)}. You can download
                it now or later from the table.
              </p>

              <div className="toolbar-actions">
                <a
                  className="artifact-link"
                  href={getSavedAudioDownloadUrl(latestSaved.id)}
                >
                  Download now
                </a>
                <a
                  className="artifact-link"
                  href={latestSaved.youtube_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  Open source video
                </a>
              </div>
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
            Public videos may still work anonymously, but this flow is designed to
            take advantage of the managed authenticated path when YouTube gets picky.
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

      <section className="panel panel-body">
        <div className="section-heading">
          <div>
            <p className="eyebrow">History</p>
            <h2>Saved audio downloads</h2>
          </div>
          <span className="mono-tag">{downloads.length} saved</span>
        </div>

        <p className="panel-copy">
          Each row stays available until you delete it, so you can re-download the
          artifact without hitting YouTube again.
        </p>

        {downloadsLoading ? <p className="state-message">Loading saved audio…</p> : null}
        {downloadsError !== null ? <p className="inline-error">{downloadsError}</p> : null}

        {!downloadsLoading && downloads.length === 0 ? (
          <p className="state-message">No saved audio downloads yet.</p>
        ) : null}

        {downloads.length > 0 ? (
          <div className="data-table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Saved</th>
                  <th>Title</th>
                  <th>Preset</th>
                  <th>Duration</th>
                  <th>Size</th>
                  <th>Auth</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {downloads.map((download) => (
                  <tr key={download.id}>
                    <td>{formatDateTime(download.created_at)}</td>
                    <td>
                      <div className="table-primary">{download.title}</div>
                      <div className="table-secondary">{download.channel_name}</div>
                    </td>
                    <td>
                      <span className="mono-tag">{presetLabel(download.preset)}</span>
                    </td>
                    <td>{formatDuration(download.duration_seconds)}</td>
                    <td>{formatBytes(download.file_size_bytes)}</td>
                    <td>
                      <span className={`status-pill ${youtubeAuthTone(download.auth_mode)}`}>
                        {formatYouTubeAuthMode(download.auth_mode)}
                      </span>
                    </td>
                    <td>
                      <div className="row-actions">
                        <a
                          className="artifact-link"
                          href={getSavedAudioDownloadUrl(download.id)}
                        >
                          Download
                        </a>
                        <a
                          className="artifact-link"
                          href={download.youtube_url}
                          target="_blank"
                          rel="noreferrer"
                        >
                          YouTube
                        </a>
                        <button
                          type="button"
                          className="button secondary"
                          disabled={deletingId === download.id}
                          onClick={() => {
                            void handleDelete(download);
                          }}
                        >
                          {deletingId === download.id ? "Deleting…" : "Delete"}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>
    </section>
  );
}

function presetLabel(preset: AudioDownloadPreset): string {
  return presetOptions.find((option) => option.value === preset)?.label ?? preset;
}
