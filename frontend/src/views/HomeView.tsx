import {
  type ChangeEvent,
  type FormEvent,
  startTransition,
  useDeferredValue,
  useEffect,
  useState,
} from "react";
import { Link, useNavigate } from "react-router-dom";

import {
  getAdminOverview,
  ingestVideo,
  listVideos,
  type IngestRequest,
  type OverviewResponse,
  type VideoSummary,
} from "../api";
import {
  formatCompactNumber,
  formatDateTime,
  formatDuration,
  formatStatusLabel,
  statusTone,
} from "../format";

const initialFormState: IngestRequest = {
  youtube_url: "",
  extract_frames: true,
  extract_audio_chunks: true,
  extract_video_chunks: false,
  language_hint: null,
  max_resolution: 720,
};

export function HomeView() {
  const navigate = useNavigate();
  const [overview, setOverview] = useState<OverviewResponse | null>(null);
  const [videos, setVideos] = useState<VideoSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<
    "all" | "completed" | "in_progress" | "failed" | "pending"
  >("all");
  const deferredSearch = useDeferredValue(search);

  const [formState, setFormState] = useState(initialFormState);
  const [submitState, setSubmitState] = useState<"idle" | "submitting">("idle");
  const [submitError, setSubmitError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();

    async function loadData() {
      setLoading(true);
      setError(null);

      try {
        const [nextOverview, nextVideos] = await Promise.all([
          getAdminOverview(),
          listVideos(),
        ]);

        if (controller.signal.aborted) {
          return;
        }

        setOverview(nextOverview);
        setVideos(nextVideos.videos);
      } catch (loadError) {
        if (!controller.signal.aborted) {
          setError(
            loadError instanceof Error
              ? loadError.message
              : "Could not load the current library state.",
          );
        }
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      }
    }

    void loadData();

    return () => controller.abort();
  }, [reloadToken]);

  const visibleVideos = videos.filter((video) => {
    const matchesStatus =
      statusFilter === "all" ? true : video.status === statusFilter;
    const matchesSearch =
      deferredSearch.trim().length === 0
        ? true
        : `${video.title} ${video.youtube_id}`
            .toLowerCase()
            .includes(deferredSearch.trim().toLowerCase());
    return matchesStatus && matchesSearch;
  });

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitState("submitting");
    setSubmitError(null);

    try {
      const result = await ingestVideo(formState);
      setFormState(initialFormState);
      startTransition(() => {
        navigate(`/videos/${result.video_id}`);
      });
    } catch (submitFailure) {
      setSubmitError(
        submitFailure instanceof Error
          ? submitFailure.message
          : "The ingest request failed.",
      );
    } finally {
      setSubmitState("idle");
    }
  }

  function updateTextField(
    field: keyof Pick<IngestRequest, "youtube_url" | "max_resolution">,
    value: string,
  ) {
    setFormState((current) => ({
      ...current,
      [field]:
        field === "max_resolution" ? Math.max(144, Number(value || 720)) : value,
    }));
  }

  function updateCheckbox(
    field: keyof Pick<
      IngestRequest,
      "extract_frames" | "extract_audio_chunks" | "extract_video_chunks"
    >,
    checked: boolean,
  ) {
    setFormState((current) => ({
      ...current,
      [field]: checked,
    }));
  }

  function updateLanguageHint(event: ChangeEvent<HTMLInputElement>) {
    const value = event.target.value.trim();
    setFormState((current) => ({
      ...current,
      language_hint: value.length > 0 ? value : null,
    }));
  }

  return (
    <section className="page-stack">
      <div className="hero panel">
        <div>
          <p className="eyebrow">WireGuard only</p>
          <h1>Inspect what is already indexed, and push new videos in.</h1>
          <p className="hero-copy">
            The dashboard stays focused on your personal library: inventory,
            processing state, chunk counts, and direct drill-down into the
            indexed timeline.
          </p>
        </div>
        <button
          type="button"
          className="button secondary"
          onClick={() => {
            startTransition(() => {
              setReloadToken((current) => current + 1);
            });
          }}
        >
          Refresh snapshot
        </button>
      </div>

      <div className="summary-grid">
        <StatCard
          label="Library"
          value={formatCompactNumber(overview?.total_videos ?? 0)}
          caption={`latest ${formatDateTime(overview?.latest_ingestion_at ?? null)}`}
        />
        <StatCard
          label="Ready"
          value={formatCompactNumber(overview?.videos_by_status.completed ?? 0)}
          caption="fully queryable"
          tone="success"
        />
        <StatCard
          label="Processing"
          value={formatCompactNumber(overview?.videos_by_status.in_progress ?? 0)}
          caption="still running pipeline"
          tone="warning"
        />
        <StatCard
          label="Failed"
          value={formatCompactNumber(overview?.videos_by_status.failed ?? 0)}
          caption="needs a look"
          tone="danger"
        />
        <StatCard
          label="Chunks"
          value={formatCompactNumber(overview?.total_chunks ?? 0)}
          caption={`${overview?.chunks_by_modality.transcript ?? 0} transcript / ${overview?.chunks_by_modality.frame ?? 0} frame`}
        />
      </div>

      <div className="content-grid">
        <form className="panel form-panel" onSubmit={handleSubmit}>
          <div className="section-heading">
            <div>
              <p className="eyebrow">Ingest</p>
              <h2>Add another video</h2>
            </div>
            <span className="mono-tag">POST /v1/videos/ingest</span>
          </div>

          <label className="field">
            <span>YouTube URL</span>
            <input
              required
              type="url"
              placeholder="https://www.youtube.com/watch?v=..."
              value={formState.youtube_url}
              onChange={(event) => updateTextField("youtube_url", event.target.value)}
            />
          </label>

          <div className="field-row">
            <label className="field">
              <span>Language hint</span>
              <input
                type="text"
                placeholder="es"
                value={formState.language_hint ?? ""}
                onChange={updateLanguageHint}
              />
            </label>
            <label className="field">
              <span>Max resolution</span>
              <input
                type="number"
                min={144}
                max={2160}
                step={1}
                value={formState.max_resolution}
                onChange={(event) =>
                  updateTextField("max_resolution", event.target.value)
                }
              />
            </label>
          </div>

          <div className="toggle-grid">
            <ToggleField
              label="Extract frames"
              checked={formState.extract_frames}
              onChange={(checked) => updateCheckbox("extract_frames", checked)}
            />
            <ToggleField
              label="Audio chunks"
              checked={formState.extract_audio_chunks}
              onChange={(checked) => updateCheckbox("extract_audio_chunks", checked)}
            />
            <ToggleField
              label="Video chunks"
              checked={formState.extract_video_chunks}
              onChange={(checked) => updateCheckbox("extract_video_chunks", checked)}
            />
          </div>

          {submitError !== null ? <p className="inline-error">{submitError}</p> : null}

          <button
            type="submit"
            className="button primary"
            disabled={submitState === "submitting"}
          >
            {submitState === "submitting" ? "Submitting…" : "Start ingest"}
          </button>
        </form>

        <section className="panel">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Library</p>
              <h2>Saved videos</h2>
            </div>
            <span className="mono-tag">{visibleVideos.length} visible</span>
          </div>

          <div className="toolbar">
            <label className="field toolbar-field">
              <span>Search</span>
              <input
                type="search"
                placeholder="title or YouTube ID"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
            </label>

            <label className="field toolbar-field">
              <span>Status</span>
              <select
                value={statusFilter}
                onChange={(event) =>
                  setStatusFilter(
                    event.target.value as
                      | "all"
                      | "completed"
                      | "in_progress"
                      | "failed"
                      | "pending",
                  )
                }
              >
                <option value="all">all</option>
                <option value="completed">completed</option>
                <option value="in_progress">in progress</option>
                <option value="failed">failed</option>
                <option value="pending">pending</option>
              </select>
            </label>
          </div>

          {loading ? <p className="state-message">Loading current library…</p> : null}
          {error !== null ? <p className="inline-error">{error}</p> : null}

          {!loading && error === null && visibleVideos.length === 0 ? (
            <p className="state-message">No videos match the current filter.</p>
          ) : null}

          <div className="video-grid">
            {visibleVideos.map((video) => (
              <Link
                key={video.id}
                to={`/videos/${video.id}`}
                className="video-card"
              >
                <div className="video-card-head">
                  <span className={`status-pill ${statusTone(video.status)}`}>
                    {formatStatusLabel(video.status)}
                  </span>
                  <span className="mono-tag">{video.youtube_id}</span>
                </div>

                <h3>{video.title}</h3>

                <dl className="meta-grid">
                  <div>
                    <dt>Duration</dt>
                    <dd>{formatDuration(video.duration_seconds)}</dd>
                  </div>
                  <div>
                    <dt>Indexed</dt>
                    <dd>{formatDateTime(video.created_at)}</dd>
                  </div>
                  <div>
                    <dt>Transcript</dt>
                    <dd>{video.chunk_counts.transcript ?? 0}</dd>
                  </div>
                  <div>
                    <dt>Frames</dt>
                    <dd>{video.chunk_counts.frame ?? 0}</dd>
                  </div>
                </dl>
              </Link>
            ))}
          </div>
        </section>
      </div>
    </section>
  );
}

function StatCard({
  label,
  value,
  caption,
  tone = "neutral",
}: {
  label: string;
  value: string;
  caption: string;
  tone?: string;
}) {
  return (
    <article className={`panel stat-card ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{caption}</small>
    </article>
  );
}

function ToggleField({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="toggle-field">
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span>{label}</span>
    </label>
  );
}
