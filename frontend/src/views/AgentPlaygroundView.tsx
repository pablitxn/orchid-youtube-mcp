import {
  type FormEvent,
  startTransition,
  useEffect,
  useState,
} from "react";
import { Link, useSearchParams } from "react-router-dom";

import {
  chatWithVideoAgent,
  getAdminVideoDetail,
  listVideos,
  type AdminVideoDetail,
  type AgentChatMessage,
  type AgentToolTrace,
  type VideoSummary,
} from "../api";
import {
  formatDateTime,
  formatDuration,
  formatStatusLabel,
  statusTone,
} from "../format";

interface PlaygroundMessage extends AgentChatMessage {
  responseId?: string | null;
  toolTraces?: AgentToolTrace[];
}

export function AgentPlaygroundView() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [videos, setVideos] = useState<VideoSummary[]>([]);
  const [detail, setDetail] = useState<AdminVideoDetail | null>(null);
  const [loadingVideos, setLoadingVideos] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [videosError, setVideosError] = useState<string | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [chatError, setChatError] = useState<string | null>(null);
  const [chatState, setChatState] = useState<"idle" | "running">("idle");
  const [composerText, setComposerText] = useState("");
  const [pendingPrompt, setPendingPrompt] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const [conversations, setConversations] = useState<
    Record<string, PlaygroundMessage[]>
  >({});

  const selectedVideoId = searchParams.get("videoId");
  const selectedVideo =
    selectedVideoId === null
      ? null
      : videos.find((video) => video.id === selectedVideoId) ?? null;
  const conversation =
    selectedVideoId === null ? [] : (conversations[selectedVideoId] ?? []);

  useEffect(() => {
    let cancelled = false;

    async function loadVideos() {
      setLoadingVideos(true);
      setVideosError(null);

      try {
        const response = await listVideos();
        if (cancelled) {
          return;
        }
        setVideos(response.videos);
      } catch (loadError) {
        if (!cancelled) {
          setVideosError(
            loadError instanceof Error
              ? loadError.message
              : "Could not load the indexed videos.",
          );
        }
      } finally {
        if (!cancelled) {
          setLoadingVideos(false);
        }
      }
    }

    void loadVideos();

    return () => {
      cancelled = true;
    };
  }, [reloadToken]);

  useEffect(() => {
    if (videos.length === 0) {
      return;
    }

    const hasSelectedVideo =
      selectedVideoId !== null &&
      videos.some((video) => video.id === selectedVideoId);

    if (hasSelectedVideo) {
      return;
    }

    startTransition(() => {
      setSearchParams({ videoId: videos[0].id }, { replace: true });
    });
  }, [searchParams, selectedVideoId, setSearchParams, videos]);

  useEffect(() => {
    if (selectedVideoId === null) {
      setDetail(null);
      setDetailError(null);
      return;
    }

    const currentVideoId = selectedVideoId;
    let cancelled = false;

    async function loadDetail() {
      setLoadingDetail(true);
      setDetailError(null);

      try {
        const response = await getAdminVideoDetail(currentVideoId);
        if (cancelled) {
          return;
        }
        setDetail(response);
      } catch (loadError) {
        if (!cancelled) {
          setDetail(null);
          setDetailError(
            loadError instanceof Error
              ? loadError.message
              : "Could not load the selected video detail.",
          );
        }
      } finally {
        if (!cancelled) {
          setLoadingDetail(false);
        }
      }
    }

    void loadDetail();

    return () => {
      cancelled = true;
    };
  }, [selectedVideoId]);

  async function handleChatSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (selectedVideoId === null) {
      setChatError("Select a video first.");
      return;
    }

    const prompt = composerText.trim();
    if (prompt.length === 0) {
      setChatError("Write a message first.");
      return;
    }

    const nextHistory: PlaygroundMessage[] = [
      ...conversation,
      { role: "user", content: prompt },
    ];

    setChatState("running");
    setChatError(null);
    setComposerText("");
    setPendingPrompt(prompt);

    try {
      const response = await chatWithVideoAgent(selectedVideoId, nextHistory);
      const assistantMessage: PlaygroundMessage = {
        role: "assistant",
        content: response.reply,
        responseId: response.response_id,
        toolTraces: response.tool_traces,
      };

      setConversations((current) => ({
        ...current,
        [selectedVideoId]: [...nextHistory, assistantMessage],
      }));
    } catch (failure) {
      setComposerText(prompt);
      setChatError(
        failure instanceof Error ? failure.message : "The agent request failed.",
      );
    } finally {
      setPendingPrompt(null);
      setChatState("idle");
    }
  }

  function selectVideo(videoId: string) {
    startTransition(() => {
      setSearchParams({ videoId });
      setChatError(null);
    });
  }

  function resetChat() {
    if (selectedVideoId === null) {
      return;
    }

    setConversations((current) => {
      const nextState = { ...current };
      delete nextState[selectedVideoId];
      return nextState;
    });
    setChatError(null);
    setPendingPrompt(null);
    setComposerText("");
  }

  return (
    <section className="page-stack">
      <div className="hero panel compact">
        <div>
          <p className="eyebrow">Agent playground</p>
          <h1>Chat with one indexed video through the same MCP.</h1>
          <p className="hero-copy">
            Pick a saved video, render it inline, and test a grounded agent that
            calls the exact MCP tools backing the app.
          </p>
        </div>
        <button
          type="button"
          className="button secondary"
          onClick={() => setReloadToken((current) => current + 1)}
        >
          Refresh library
        </button>
      </div>

      {videosError !== null ? <p className="inline-error">{videosError}</p> : null}

      <div className="playground-layout">
        <aside className="panel video-sidebar">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Videos</p>
              <h2>Choose the target</h2>
            </div>
            <span className="mono-tag">{videos.length} indexed</span>
          </div>

          {loadingVideos ? (
            <p className="state-message">Loading video list…</p>
          ) : null}

          {!loadingVideos && videos.length === 0 ? (
            <p className="state-message">
              No indexed videos yet. Add one from the{" "}
              <Link to="/">library dashboard</Link>.
            </p>
          ) : null}

          <div className="video-list">
            {videos.map((video) => (
              <button
                key={video.id}
                type="button"
                className={`video-list-item ${
                  selectedVideoId === video.id ? "active" : ""
                }`}
                onClick={() => selectVideo(video.id)}
              >
                <div className="video-list-head">
                  <span className={`status-pill ${statusTone(video.status)}`}>
                    {formatStatusLabel(video.status)}
                  </span>
                  <span className="mono-tag">{video.youtube_id}</span>
                </div>
                <strong>{video.title}</strong>
                <div className="pill-row">
                  <span className="mono-tag">
                    {formatDuration(video.duration_seconds)}
                  </span>
                  <span className="mono-tag">
                    {Object.values(video.chunk_counts).reduce(
                      (total, count) => total + count,
                      0,
                    )}{" "}
                    chunks
                  </span>
                </div>
                <small>{formatDateTime(video.created_at)}</small>
              </button>
            ))}
          </div>
        </aside>

        <div className="page-stack">
          <section className="panel player-panel">
            {loadingDetail ? (
              <p className="state-message">Loading selected video…</p>
            ) : null}
            {detailError !== null ? <p className="inline-error">{detailError}</p> : null}

            {detail !== null ? (
              <div className="player-grid">
                <div className="player-frame">
                  <iframe
                    src={`https://www.youtube.com/embed/${detail.youtube_id}?rel=0&modestbranding=1`}
                    title={detail.title}
                    allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
                    allowFullScreen
                  />
                </div>

                <div className="player-meta">
                  <div className="section-heading">
                    <div>
                      <p className="eyebrow">Selected video</p>
                      <h2>{detail.title}</h2>
                    </div>
                    <span className={`status-pill ${statusTone(detail.processing_state)}`}>
                      {formatStatusLabel(detail.processing_state)}
                    </span>
                  </div>

                  <p className="hero-copy">
                    {detail.description || "No description saved."}
                  </p>

                  <div className="pill-row">
                    <span className="mono-tag">{detail.channel_name}</span>
                    <span className="mono-tag">{detail.duration_display}</span>
                    <span className="mono-tag">{detail.total_chunks} chunks</span>
                    {detail.language !== null ? (
                      <span className="mono-tag">lang {detail.language}</span>
                    ) : null}
                  </div>

                  <dl className="meta-grid">
                    <div>
                      <dt>Internal ID</dt>
                      <dd>{detail.id}</dd>
                    </div>
                    <div>
                      <dt>YouTube upload</dt>
                      <dd>{formatDateTime(detail.upload_date)}</dd>
                    </div>
                    <div>
                      <dt>Indexed at</dt>
                      <dd>{formatDateTime(detail.created_at)}</dd>
                    </div>
                    <div>
                      <dt>Updated at</dt>
                      <dd>{formatDateTime(detail.updated_at)}</dd>
                    </div>
                  </dl>

                  <div className="toolbar-actions">
                    <a
                      className="button secondary link-button"
                      href={detail.youtube_url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Open on YouTube
                    </a>
                    <Link
                      className="button secondary link-button"
                      to={`/videos/${detail.id}`}
                    >
                      Open detail view
                    </Link>
                  </div>
                </div>
              </div>
            ) : null}
          </section>

          <section className="panel chat-panel">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Chat</p>
                <h2>Selected-video agent</h2>
              </div>
              <div className="toolbar-actions">
                <span className="mono-tag">
                  {selectedVideo?.title ?? "No video selected"}
                </span>
                <button
                  type="button"
                  className="button secondary"
                  disabled={selectedVideoId === null || conversation.length === 0}
                  onClick={resetChat}
                >
                  Reset chat
                </button>
              </div>
            </div>

            <div className="chat-log">
              {conversation.length === 0 && pendingPrompt === null ? (
                <p className="state-message">
                  Start with something concrete like “what happens in the first two
                  minutes?” or “show me the citations for the visual explanation”.
                </p>
              ) : null}

              {conversation.map((message, index) => (
                <ChatMessageCard
                  key={`${message.role}-${index}-${message.content.slice(0, 32)}`}
                  message={message}
                />
              ))}

              {pendingPrompt !== null ? (
                <article className="chat-bubble user pending">
                  <header>
                    <strong>You</strong>
                    <span className="mono-tag">sending</span>
                  </header>
                  <p>{pendingPrompt}</p>
                </article>
              ) : null}
            </div>

            {chatError !== null ? <p className="inline-error">{chatError}</p> : null}

            <form className="chat-composer" onSubmit={handleChatSubmit}>
              <label className="field">
                <span>Message</span>
                <textarea
                  rows={4}
                  placeholder="Ask about content, timestamps, visuals, or request sources."
                  value={composerText}
                  onChange={(event) => setComposerText(event.target.value)}
                  disabled={selectedVideoId === null || chatState === "running"}
                />
              </label>

              <div className="toolbar-actions">
                <button
                  type="submit"
                  className="button primary"
                  disabled={selectedVideoId === null || chatState === "running"}
                >
                  {chatState === "running" ? "Thinking…" : "Send message"}
                </button>
              </div>
            </form>
          </section>
        </div>
      </div>
    </section>
  );
}

function ChatMessageCard({ message }: { message: PlaygroundMessage }) {
  return (
    <article className={`chat-bubble ${message.role}`}>
      <header>
        <strong>{message.role === "assistant" ? "Agent" : "You"}</strong>
        {message.responseId ? (
          <span className="mono-tag">{message.responseId}</span>
        ) : null}
      </header>
      <p>{message.content}</p>

      {message.toolTraces !== undefined && message.toolTraces.length > 0 ? (
        <div className="trace-list">
          {message.toolTraces.map((trace, index) => (
            <article
              key={`${trace.tool_name}-${trace.mcp_tool_name}-${index}`}
              className="trace-card"
            >
              <div className="trace-head">
                <strong>{trace.tool_name}</strong>
                <span className="mono-tag">{trace.mcp_tool_name}</span>
              </div>
              <pre>{JSON.stringify(trace.arguments, null, 2)}</pre>
              <p>{trace.result_preview}</p>
            </article>
          ))}
        </div>
      ) : null}
    </article>
  );
}
