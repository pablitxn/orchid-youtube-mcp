import {
  type FormEvent,
  startTransition,
  useEffect,
  useState,
} from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  deleteVideo,
  getAdminVideoDetail,
  getSources,
  getVideoChunks,
  queryVideo,
  type AdminArtifact,
  type AdminChunksResponse,
  type AdminVideoDetail,
  type ChunkItem,
  type Modality,
  type QueryResponse,
  type SourceDetail,
} from "../api";
import {
  formatDateTime,
  formatStatusLabel,
  statusTone,
} from "../format";

type ChunkFilter = Modality | "all";

const defaultModalities: Modality[] = ["transcript", "frame"];

export function VideoView() {
  const navigate = useNavigate();
  const { videoId } = useParams<{ videoId: string }>();
  const [detail, setDetail] = useState<AdminVideoDetail | null>(null);
  const [chunks, setChunks] = useState<AdminChunksResponse | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [chunksError, setChunksError] = useState<string | null>(null);
  const [detailLoading, setDetailLoading] = useState(true);
  const [chunksLoading, setChunksLoading] = useState(false);
  const [chunkFilter, setChunkFilter] = useState<ChunkFilter>("transcript");
  const [refreshToken, setRefreshToken] = useState(0);

  const [queryText, setQueryText] = useState("");
  const [queryModalities, setQueryModalities] =
    useState<Modality[]>(defaultModalities);
  const [maxCitations, setMaxCitations] = useState(5);
  const [includeReasoning, setIncludeReasoning] = useState(true);
  const [queryState, setQueryState] = useState<"idle" | "running">("idle");
  const [queryError, setQueryError] = useState<string | null>(null);
  const [queryResult, setQueryResult] = useState<QueryResponse | null>(null);
  const [sourceMap, setSourceMap] = useState<Record<string, SourceDetail>>({});

  const [deleteState, setDeleteState] = useState<"idle" | "deleting">("idle");

  useEffect(() => {
    if (videoId === undefined) {
      return;
    }
    const currentVideoId = videoId;

    const controller = new AbortController();

    async function loadDetail() {
      setDetailLoading(true);
      setDetailError(null);

      try {
        const response = await getAdminVideoDetail(currentVideoId);
        if (!controller.signal.aborted) {
          setDetail(response);
        }
      } catch (loadError) {
        if (!controller.signal.aborted) {
          setDetailError(
            loadError instanceof Error
              ? loadError.message
              : "Could not load the video detail.",
          );
        }
      } finally {
        if (!controller.signal.aborted) {
          setDetailLoading(false);
        }
      }
    }

    void loadDetail();

    return () => controller.abort();
  }, [videoId, refreshToken]);

  useEffect(() => {
    if (videoId === undefined) {
      return;
    }
    const currentVideoId = videoId;

    const controller = new AbortController();

    async function loadChunks() {
      setChunksLoading(true);
      setChunksError(null);

      try {
        const response = await getVideoChunks(currentVideoId, chunkFilter);
        if (!controller.signal.aborted) {
          setChunks(response);
        }
      } catch (loadError) {
        if (!controller.signal.aborted) {
          setChunksError(
            loadError instanceof Error
              ? loadError.message
              : "Could not load indexed chunks.",
          );
        }
      } finally {
        if (!controller.signal.aborted) {
          setChunksLoading(false);
        }
      }
    }

    void loadChunks();

    return () => controller.abort();
  }, [videoId, chunkFilter, refreshToken]);

  if (videoId === undefined) {
    return <p className="inline-error">No video selected.</p>;
  }

  async function handleQuery(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (videoId === undefined) {
      return;
    }
    if (queryText.trim().length === 0) {
      setQueryError("Write a question first.");
      return;
    }

    setQueryState("running");
    setQueryError(null);

    try {
      const result = await queryVideo(videoId, {
        query: queryText.trim(),
        modalities: queryModalities,
        max_citations: maxCitations,
        include_reasoning: includeReasoning,
      });
      setQueryResult(result);

      if (result.citations.length > 0) {
        const sources = await getSources(
          videoId,
          result.citations.map((citation) => citation.id),
        );
        const mappedSources = Object.fromEntries(
          sources.sources.map((source) => [source.citation_id, source]),
        );
        setSourceMap(mappedSources);
      } else {
        setSourceMap({});
      }
    } catch (failure) {
      setQueryError(
        failure instanceof Error ? failure.message : "The query failed.",
      );
    } finally {
      setQueryState("idle");
    }
  }

  async function handleDelete() {
    if (
      videoId === undefined ||
      detail === null ||
      !window.confirm(`Delete "${detail.title}" and every stored artifact?`)
    ) {
      return;
    }

    setDeleteState("deleting");

    try {
      await deleteVideo(videoId);
      startTransition(() => {
        navigate("/");
      });
    } catch (failure) {
      setDetailError(
        failure instanceof Error ? failure.message : "Could not delete the video.",
      );
      setDeleteState("idle");
    }
  }

  function toggleQueryModality(modality: Modality) {
    setQueryModalities((current) => {
      if (current.includes(modality)) {
        if (current.length === 1) {
          return current;
        }
        return current.filter((item) => item !== modality);
      }
      return [...current, modality];
    });
  }

  return (
    <section className="page-stack">
      <div className="detail-toolbar">
        <Link to="/" className="ghost-link">
          ← Back to library
        </Link>
        <div className="toolbar-actions">
          <Link to={`/agent?videoId=${videoId}`} className="button secondary">
            Open agent
          </Link>
          <button
            type="button"
            className="button secondary"
            onClick={() => setRefreshToken((current) => current + 1)}
          >
            Refresh
          </button>
          <button
            type="button"
            className="button danger"
            disabled={deleteState === "deleting"}
            onClick={() => {
              void handleDelete();
            }}
          >
            {deleteState === "deleting" ? "Deleting…" : "Delete video"}
          </button>
        </div>
      </div>

      {detailLoading ? <p className="state-message">Loading video detail…</p> : null}
      {detailError !== null ? <p className="inline-error">{detailError}</p> : null}

      {detail !== null ? (
        <>
          <section className="panel detail-hero">
            <div className="detail-heading">
              <div>
                <p className="eyebrow">Video detail</p>
                <h1>{detail.title}</h1>
              </div>
              <span className={`status-pill ${statusTone(detail.status)}`}>
                {formatStatusLabel(detail.status)}
              </span>
            </div>

            <p className="hero-copy">{detail.description || "No description saved."}</p>

            <div className="pill-row">
              <span className="mono-tag">{detail.youtube_id}</span>
              <span className="mono-tag">
                state {formatStatusLabel(detail.processing_state)}
              </span>
              <span className="mono-tag">duration {detail.duration_display}</span>
              <span className="mono-tag">channel {detail.channel_name}</span>
              {detail.language !== null ? (
                <span className="mono-tag">lang {detail.language}</span>
              ) : null}
            </div>

            <dl className="meta-grid spacious">
              <div>
                <dt>Indexed at</dt>
                <dd>{formatDateTime(detail.created_at)}</dd>
              </div>
              <div>
                <dt>Updated at</dt>
                <dd>{formatDateTime(detail.updated_at)}</dd>
              </div>
              <div>
                <dt>YouTube upload</dt>
                <dd>{formatDateTime(detail.upload_date)}</dd>
              </div>
              <div>
                <dt>Total chunks</dt>
                <dd>{detail.total_chunks}</dd>
              </div>
            </dl>

            {detail.error_message !== null ? (
              <p className="inline-error">{detail.error_message}</p>
            ) : null}

            <div className="artifact-list">
              <a
                className="artifact-link"
                href={detail.youtube_url}
                target="_blank"
                rel="noreferrer"
              >
                Open on YouTube
              </a>
              {detail.artifacts
                .filter((artifact) => artifact.url !== null)
                .map((artifact) => (
                  <a
                    key={`${artifact.type}-${artifact.path ?? artifact.url}`}
                    className="artifact-link"
                    href={artifact.url ?? undefined}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {artifact.label}
                  </a>
                ))}
            </div>
          </section>

          <section className="panel panel-body">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Indexed timeline</p>
                <h2>Chunks and saved artifacts</h2>
              </div>
              <span className="mono-tag">
                {chunks?.pagination.total_items ?? 0} loaded
              </span>
            </div>

            <div className="filter-row">
              {(["transcript", "frame", "audio", "video", "all"] as ChunkFilter[]).map(
                (filter) => (
                  <button
                    key={filter}
                    type="button"
                    className={`filter-chip ${chunkFilter === filter ? "active" : ""}`}
                    onClick={() => {
                      startTransition(() => {
                        setChunkFilter(filter);
                      });
                    }}
                  >
                    {filter}
                    {filter !== "all" ? ` ${detail.chunk_counts[filter] ?? 0}` : ""}
                  </button>
                ),
              )}
            </div>

            {chunksLoading ? (
              <p className="state-message">Loading indexed chunks…</p>
            ) : null}
            {chunksError !== null ? <p className="inline-error">{chunksError}</p> : null}

            <div className="chunk-grid">
              {chunks?.chunks.map((chunk) => (
                <ChunkCard key={chunk.id} chunk={chunk} />
              ))}
            </div>
          </section>

          <section className="panel panel-body">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Query playground</p>
                <h2>Ask the current index</h2>
              </div>
              <span className="mono-tag">POST /v1/videos/{videoId}/query</span>
            </div>

            <form className="query-form" onSubmit={handleQuery}>
              <label className="field">
                <span>Question</span>
                <textarea
                  rows={4}
                  placeholder="What is happening in the first minute?"
                  value={queryText}
                  onChange={(event) => setQueryText(event.target.value)}
                />
              </label>

              <div className="toggle-grid">
                {(["transcript", "frame", "audio", "video"] as Modality[]).map(
                  (modality) => (
                    <ToggleField
                      key={modality}
                      label={modality}
                      checked={queryModalities.includes(modality)}
                      onChange={() => toggleQueryModality(modality)}
                    />
                  ),
                )}
              </div>

              <div className="field-row">
                <label className="field">
                  <span>Max citations</span>
                  <input
                    type="number"
                    min={1}
                    max={20}
                    value={maxCitations}
                    onChange={(event) => setMaxCitations(Number(event.target.value))}
                  />
                </label>

                <label className="toggle-field inline-toggle">
                  <input
                    type="checkbox"
                    checked={includeReasoning}
                    onChange={(event) => setIncludeReasoning(event.target.checked)}
                  />
                  <span>Include reasoning</span>
                </label>
              </div>

              {queryError !== null ? <p className="inline-error">{queryError}</p> : null}

              <button
                type="submit"
                className="button primary"
                disabled={queryState === "running"}
              >
                {queryState === "running" ? "Running query…" : "Run query"}
              </button>
            </form>

            {queryResult !== null ? (
              <div className="query-result">
                <div className="answer-card">
                  <p className="eyebrow">Answer</p>
                  <h3>{queryResult.query_metadata.video_title}</h3>
                  <p>{queryResult.answer}</p>
                  {queryResult.reasoning !== null ? (
                    <div className="reasoning-block">
                      <strong>Reasoning</strong>
                      <p>{queryResult.reasoning}</p>
                    </div>
                  ) : null}
                  <div className="pill-row">
                    <span className="mono-tag">
                      confidence {(queryResult.confidence * 100).toFixed(1)}%
                    </span>
                    <span className="mono-tag">
                      chunks {queryResult.query_metadata.chunks_analyzed}
                    </span>
                    <span className="mono-tag">
                      {queryResult.query_metadata.processing_time_ms} ms
                    </span>
                  </div>
                </div>

                <div className="citation-stack">
                  {queryResult.citations.map((citation) => (
                    <CitationCard
                      key={citation.id}
                      citation={citation}
                      source={sourceMap[citation.id]}
                    />
                  ))}
                </div>
              </div>
            ) : null}
          </section>
        </>
      ) : null}
    </section>
  );
}

function ChunkCard({ chunk }: { chunk: ChunkItem }) {
  const transcriptArtifact = chunk.artifacts.find(
    (artifact) => artifact.type === "transcript_text",
  );
  const thumbnailArtifact = chunk.artifacts.find(
    (artifact) => artifact.type === "thumbnail",
  );
  const frameArtifact = chunk.artifacts.find(
    (artifact) => artifact.type === "frame_image",
  );
  const audioArtifact = chunk.artifacts.find(
    (artifact) => artifact.type === "audio_clip",
  );
  const videoArtifact = chunk.artifacts.find(
    (artifact) => artifact.type === "video_clip",
  );

  return (
    <article className={`chunk-card ${chunk.modality}`}>
      <div className="chunk-card-head">
        <span className="mono-tag">{chunk.modality}</span>
        <a href={chunk.youtube_url} target="_blank" rel="noreferrer">
          {chunk.timestamp}
        </a>
      </div>

      {(thumbnailArtifact?.url ?? frameArtifact?.url) !== undefined &&
      (thumbnailArtifact?.url ?? frameArtifact?.url) !== null ? (
        <img
          className="chunk-preview"
          src={(thumbnailArtifact?.url ?? frameArtifact?.url) ?? undefined}
          alt={`${chunk.modality} preview`}
          loading="lazy"
        />
      ) : null}

      {audioArtifact?.url !== null && audioArtifact?.url !== undefined ? (
        <audio controls preload="none" src={audioArtifact.url} />
      ) : null}

      {videoArtifact?.url !== null && videoArtifact?.url !== undefined ? (
        <video controls preload="metadata" src={videoArtifact.url} />
      ) : null}

      <h3>{chunk.preview}</h3>

      {transcriptArtifact?.content !== null &&
      transcriptArtifact?.content !== undefined ? (
        <details className="text-artifact">
          <summary>Transcript text</summary>
          <p>{transcriptArtifact.content}</p>
        </details>
      ) : null}

      <dl className="meta-grid">
        {Object.entries(chunk.metadata).map(([key, value]) => (
          <div key={key}>
            <dt>{key.replace(/_/g, " ")}</dt>
            <dd>{String(value)}</dd>
          </div>
        ))}
      </dl>
    </article>
  );
}

function CitationCard({
  citation,
  source,
}: {
  citation: QueryResponse["citations"][number];
  source: SourceDetail | undefined;
}) {
  const thumbnail = source?.artifacts.thumbnail?.url;
  const frameImage = source?.artifacts.frame_image?.url;
  const audioClip = source?.artifacts.audio_clip?.url;
  const videoClip = source?.artifacts.video_clip?.url;
  const transcriptText = source?.artifacts.transcript_text?.content;

  return (
    <article className="citation-card">
      <div className="citation-head">
        <span className="mono-tag">{citation.modality}</span>
        <a
          href={citation.youtube_url ?? "#"}
          target="_blank"
          rel="noreferrer"
          className={citation.youtube_url === null ? "disabled-link" : ""}
        >
          {citation.timestamp_range.display}
        </a>
      </div>

      <p>{citation.content_preview}</p>

      {transcriptText !== undefined && transcriptText !== null ? (
        <div className="reasoning-block">
          <strong>Source text</strong>
          <p>{transcriptText}</p>
        </div>
      ) : null}

      {(thumbnail ?? frameImage) !== undefined && (thumbnail ?? frameImage) !== null ? (
        <img
          className="citation-preview"
          src={(thumbnail ?? frameImage) ?? undefined}
          alt="Citation preview"
          loading="lazy"
        />
      ) : null}

      {audioClip !== undefined && audioClip !== null ? (
        <audio controls preload="none" src={audioClip} />
      ) : null}

      {videoClip !== undefined && videoClip !== null ? (
        <video controls preload="metadata" src={videoClip} />
      ) : null}

      <div className="pill-row">
        <span className="mono-tag">
          relevance {(citation.relevance_score * 100).toFixed(1)}%
        </span>
      </div>
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
  onChange: () => void;
}) {
  return (
    <label className="toggle-field">
      <input type="checkbox" checked={checked} onChange={onChange} />
      <span>{label}</span>
    </label>
  );
}

function ArtifactButton({ artifact }: { artifact: AdminArtifact }) {
  if (artifact.url === null) {
    return null;
  }

  return (
    <a
      className="artifact-link"
      href={artifact.url}
      target="_blank"
      rel="noreferrer"
    >
      {artifact.label}
    </a>
  );
}
