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
  audioDownloadTone,
  formatBytes,
  formatAudioDownloadState,
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
  const [youtubeUrlsText, setYoutubeUrlsText] = useState("");
  const [preset, setPreset] = useState<AudioDownloadPreset>("mp3_192");
  const [authStatus, setAuthStatus] = useState<YouTubeAuthStatus | null>(null);
  const [authError, setAuthError] = useState<string | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [downloads, setDownloads] = useState<SavedAudioDownload[]>([]);
  const [downloadsLoading, setDownloadsLoading] = useState(true);
  const [downloadsError, setDownloadsError] = useState<string | null>(null);
  const [createState, setCreateState] = useState<"idle" | "queueing">("idle");
  const [createError, setCreateError] = useState<string | null>(null);
  const [createSummary, setCreateSummary] = useState<string | null>(null);
  const [latestSavedId, setLatestSavedId] = useState<string | null>(null);
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
  const latestSaved =
    downloads.find((download) => download.id === latestSavedId) ?? null;
  const hasActiveDownloads = downloads.some(isActiveAudioDownload);
  const requestedUrls = parseYouTubeUrls(youtubeUrlsText);

  async function refreshDownloads(options?: { background?: boolean }) {
    if (!options?.background) {
      setDownloadsLoading(true);
    }
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
      if (!options?.background) {
        setDownloadsLoading(false);
      }
    }
  }

  useEffect(() => {
    if (!hasActiveDownloads) {
      return undefined;
    }

    const intervalId = window.setInterval(() => {
      void refreshDownloads({ background: true });
    }, 2500);

    return () => window.clearInterval(intervalId);
  }, [hasActiveDownloads]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (requestedUrls.length === 0) {
      setCreateError("Paste at least one supported YouTube URL.");
      setCreateSummary(null);
      return;
    }

    setCreateState("queueing");
    setCreateError(null);
    setCreateSummary(null);

    try {
      const queueResult = await queueSavedAudioDownloads(requestedUrls, preset);

      if (queueResult.queued.length > 0) {
        const queuedIds = new Set(queueResult.queued.map((download) => download.id));
        setLatestSavedId(queueResult.queued[0]?.id ?? null);
        setDownloads((currentDownloads) => [
          ...queueResult.queued,
          ...currentDownloads.filter((download) => !queuedIds.has(download.id)),
        ]);
        await refreshDownloads({ background: true });
      }

      if (queueResult.failed.length === 0) {
        setYoutubeUrlsText("");
        setCreateSummary(
          `Queued ${queueResult.queued.length} ${pluralizeAudio(queueResult.queued.length)}. Processing stays capped at 3 concurrent downloads.`,
        );
        return;
      }

      setYoutubeUrlsText(queueResult.failed.map((failure) => failure.url).join("\n"));
      setCreateError(buildQueueFailureMessage(queueResult.failed));
      if (queueResult.queued.length > 0) {
        setCreateSummary(
          `Queued ${queueResult.queued.length} ${pluralizeAudio(queueResult.queued.length)}. Left the ${queueResult.failed.length} failed ${pluralizeLine(queueResult.failed.length)} in the box so you can retry.`,
        );
      }
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
    if (
      !window.confirm(
        `Delete saved audio "${download.filename ?? download.youtube_url}"?`,
      )
    ) {
      return;
    }

    setDeletingId(download.id);
    setDownloadsError(null);

    try {
      await deleteSavedAudioDownload(download.id);
      if (latestSavedId === download.id) {
        setLatestSavedId(null);
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
            Paste one URL per line, queue the whole list in one shot, and watch the
            lifecycle progress below while the artifacts move into MinIO. Runtime
            processing is capped at 3 concurrent downloads.
          </p>

          <form className="auth-form" onSubmit={handleSubmit}>
            <label className="field">
              <span>YouTube URLs</span>
              <textarea
                required
                rows={8}
                placeholder={[
                  "https://www.youtube.com/watch?v=...",
                  "https://youtu.be/...",
                  "https://www.youtube.com/watch?v=...",
                ].join("\n")}
                value={youtubeUrlsText}
                onChange={(event) => setYoutubeUrlsText(event.target.value)}
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
            <p className="helper-copy">
              Detected {requestedUrls.length} {pluralizeLine(requestedUrls.length)} to
              queue.
            </p>

            {createError !== null ? <p className="inline-error">{createError}</p> : null}
            {createSummary !== null ? (
              <p className="state-message">{createSummary}</p>
            ) : null}

            <div className="toolbar-actions">
              <button
                type="submit"
                className="button primary"
                disabled={createState !== "idle" || requestedUrls.length === 0}
              >
                {createState === "queueing"
                  ? "Queueing…"
                  : `Queue ${requestedUrls.length || 0} ${pluralizeAudio(requestedUrls.length)}`}
              </button>
              <button
                type="button"
                className="button secondary"
                disabled={createState !== "idle" || youtubeUrlsText.length === 0}
                onClick={() => {
                  setYoutubeUrlsText("");
                  setCreateError(null);
                  setCreateSummary(null);
                }}
              >
                Clear
              </button>
            </div>
          </form>

          {latestSaved !== null ? (
            <div className="state-message">
              <div className="pill-row">
                <span className={`status-pill ${audioDownloadTone(latestSaved.state)}`}>
                  {formatAudioDownloadState(latestSaved.state)}
                </span>
                <span className={`status-pill ${youtubeAuthTone(latestSaved.auth_mode)}`}>
                  {formatYouTubeAuthMode(latestSaved.auth_mode)}
                </span>
                <span className="mono-tag">
                  {latestSaved.filename ?? presetLabel(latestSaved.preset)}
                </span>
              </div>

              <p className="helper-copy">
                {latestSaved.state_message ?? "Tracking the latest queued audio job."}
              </p>
              <p className="helper-copy">
                Queued at {formatDateTime(latestSaved.created_at)}. Last update{" "}
                {formatDateTime(latestSaved.updated_at ?? latestSaved.created_at)}.
              </p>

              {latestSaved.error_message !== null ? (
                <p className="inline-error">{latestSaved.error_message}</p>
              ) : null}

              <div className="toolbar-actions">
                {latestSaved.state === "completed" ? (
                  <a
                    className="artifact-link"
                    href={getSavedAudioDownloadUrl(latestSaved.id)}
                  >
                    Download now
                  </a>
                ) : (
                  <button
                    type="button"
                    className="button secondary"
                    onClick={() => {
                      void refreshDownloads();
                    }}
                  >
                    Refresh status
                  </button>
                )}
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
          <span className="mono-tag">{downloads.length} total</span>
        </div>

        <p className="panel-copy">
          Active jobs refresh automatically, and completed rows stay available
          until you delete them, so you can re-download the artifact later
          without hitting YouTube again.
        </p>

        {downloadsLoading ? <p className="state-message">Loading audio jobs…</p> : null}
        {downloadsError !== null ? <p className="inline-error">{downloadsError}</p> : null}

        {!downloadsLoading && downloads.length === 0 ? (
          <p className="state-message">No audio jobs yet.</p>
        ) : null}

        {downloads.length > 0 ? (
          <div className="data-table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Saved</th>
                  <th>State</th>
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
                      <span className={`status-pill ${audioDownloadTone(download.state)}`}>
                        {formatAudioDownloadState(download.state)}
                      </span>
                      <div className="table-secondary">
                        {download.state_message ?? "No status details yet."}
                      </div>
                    </td>
                    <td>
                      <div className="table-primary">
                        {download.title ?? "Resolving video details…"}
                      </div>
                      <div className="table-secondary">
                        {download.channel_name ?? download.youtube_url}
                      </div>
                      {download.error_message !== null ? (
                        <div className="table-tertiary">{download.error_message}</div>
                      ) : null}
                    </td>
                    <td>
                      <span className="mono-tag">{presetLabel(download.preset)}</span>
                    </td>
                    <td>{formatDuration(download.duration_seconds)}</td>
                    <td>{formatBytes(download.file_size_bytes)}</td>
                    <td>
                      <span
                        className={`status-pill ${youtubeAuthTone(download.auth_mode)}`}
                      >
                        {formatYouTubeAuthMode(download.auth_mode)}
                      </span>
                    </td>
                    <td>
                      <div className="row-actions">
                        {download.state === "completed" ? (
                          <a
                            className="artifact-link"
                            href={getSavedAudioDownloadUrl(download.id)}
                          >
                            Download
                          </a>
                        ) : (
                          <span className="artifact-link disabled-link">
                            {isActiveAudioDownload(download)
                              ? "Working…"
                              : "Unavailable"}
                          </span>
                        )}
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
                          disabled={
                            deletingId === download.id || isActiveAudioDownload(download)
                          }
                          onClick={() => {
                            void handleDelete(download);
                          }}
                        >
                          {deletingId === download.id
                            ? "Deleting…"
                            : isActiveAudioDownload(download)
                              ? "Running…"
                              : "Delete"}
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

function isActiveAudioDownload(download: SavedAudioDownload): boolean {
  return (
    download.state === "queued" ||
    download.state === "downloading" ||
    download.state === "uploading"
  );
}

async function queueSavedAudioDownloads(
  urls: string[],
  preset: AudioDownloadPreset,
): Promise<{
  queued: SavedAudioDownload[];
  failed: Array<{ url: string; message: string }>;
}> {
  const queued: SavedAudioDownload[] = [];
  const failed: Array<{ url: string; message: string }> = [];

  for (const batch of chunkArray(urls, 8)) {
    const batchResults = await Promise.all(
      batch.map(async (url) => {
        try {
          const savedDownload = await createSavedAudioDownload({
            youtube_url: url,
            preset,
          });
          return { ok: true as const, savedDownload };
        } catch (failure) {
          return {
            ok: false as const,
            message:
              failure instanceof Error
                ? failure.message
                : "Could not queue this YouTube URL.",
            url,
          };
        }
      }),
    );

    for (const result of batchResults) {
      if (result.ok) {
        queued.push(result.savedDownload);
        continue;
      }

      failed.push({
        url: result.url,
        message: result.message,
      });
    }
  }

  return { queued, failed };
}

function parseYouTubeUrls(input: string): string[] {
  const matches = input.match(/https?:\/\/\S+/gi) ?? [];
  const uniqueUrls = new Set<string>();

  for (const match of matches) {
    const normalized = match.replace(/[),.;]+$/u, "").trim();
    if (normalized.length > 0) {
      uniqueUrls.add(normalized);
    }
  }

  return [...uniqueUrls];
}

function chunkArray<T>(items: T[], size: number): T[][] {
  const chunks: T[][] = [];
  for (let index = 0; index < items.length; index += size) {
    chunks.push(items.slice(index, index + size));
  }
  return chunks;
}

function buildQueueFailureMessage(
  failures: Array<{ url: string; message: string }>,
): string {
  if (failures.length === 1) {
    return `${failures[0]?.message ?? "Could not queue this YouTube URL."} The failed URL stayed in the textarea.`;
  }

  const firstFailure = failures[0]?.message ?? "Could not queue some YouTube URLs.";
  return `${failures.length} URLs failed to queue. First error: ${firstFailure}`;
}

function pluralizeAudio(count: number): string {
  return count === 1 ? "audio job" : "audio jobs";
}

function pluralizeLine(count: number): string {
  return count === 1 ? "line" : "lines";
}
