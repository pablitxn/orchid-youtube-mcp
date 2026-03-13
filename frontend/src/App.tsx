import { Link, NavLink, Route, Routes } from "react-router-dom";

import { AgentPlaygroundView } from "./views/AgentPlaygroundView";
import { AudioDownloadView } from "./views/AudioDownloadView";
import { HomeView } from "./views/HomeView";
import { VideoView } from "./views/VideoView";

export default function App() {
  return (
    <div className="app-shell">
      <div className="ambient ambient-left" />
      <div className="ambient ambient-right" />
      <header className="topbar">
        <Link to="/" className="brand">
          <span className="brand-mark">YT</span>
          <span>
            <strong>YouTube MCP</strong>
            <small>personal index control room</small>
          </span>
        </Link>
        <nav className="topnav">
          <NavLink to="/" end>
            Library
          </NavLink>
          <NavLink to="/audio">Audio</NavLink>
          <NavLink to="/agent">Agent</NavLink>
          <a href="/docs" target="_blank" rel="noreferrer">
            API docs
          </a>
        </nav>
      </header>

      <main className="main-content">
        <Routes>
          <Route path="/" element={<HomeView />} />
          <Route path="/audio" element={<AudioDownloadView />} />
          <Route path="/agent" element={<AgentPlaygroundView />} />
          <Route path="/videos/:videoId" element={<VideoView />} />
        </Routes>
      </main>
    </div>
  );
}
