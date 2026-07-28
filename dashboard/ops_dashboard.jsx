import React, { useState, useEffect, useMemo, useCallback } from "react";
import Papa from "papaparse";
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, PieChart, Pie, Cell,
} from "recharts";
import {
  Upload, TrendingUp, Clock, CheckCircle2, XCircle, PlusCircle,
  Youtube, Instagram, Music2, Radar, Film,
} from "lucide-react";

// ---- design tokens ----------------------------------------------------
const C = {
  bg: "#0D1017",
  surface: "#161B26",
  surfaceAlt: "#1E2432",
  border: "#2A3142",
  text: "#E9EAEE",
  muted: "#8890A3",
  mint: "#5EE6B9",   // posted / success
  amber: "#F0B429",  // pending
  red: "#F0553D",    // failed
  violet: "#7C8CFF", // trend / discovery
};

const STAGES = [
  { key: "trend", label: "Trend", icon: Radar },
  { key: "story", label: "Story", icon: PlusCircle },
  { key: "voice", label: "Voice", icon: Music2 },
  { key: "assemble", label: "Assemble", icon: Film },
  { key: "review", label: "Review", icon: Clock },
  { key: "post", label: "Post", icon: CheckCircle2 },
];

const PLATFORM_META = {
  youtube: { label: "YouTube", color: "#F0553D", Icon: Youtube },
  instagram: { label: "Instagram", color: "#E85D9B", Icon: Instagram },
  tiktok: { label: "TikTok", color: "#5EE6B9", Icon: Music2 },
};

function statusColor(status) {
  if (status === "posted" || status === "posted_manual") return C.mint;
  if (status === "pending_review") return C.amber;
  if (status === "upload_failed") return C.red;
  return C.muted;
}

function statusLabel(status) {
  return {
    posted: "Posted",
    posted_manual: "Posted",
    pending_review: "Pending review",
    upload_failed: "Failed",
  }[status] || status;
}

export default function OpsDashboard() {
  const [posts, setPosts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [storageOk, setStorageOk] = useState(true);
  const [dragOver, setDragOver] = useState(false);
  const [metricForm, setMetricForm] = useState(null); // {id} | null

  // ---- load persisted data ----
  useEffect(() => {
    (async () => {
      try {
        const result = await window.storage.get("posts", false);
        if (result && result.value) {
          setPosts(JSON.parse(result.value));
        }
      } catch (e) {
        // key not found yet is expected on first run -- not an error
        setStorageOk(true);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const persist = useCallback(async (next) => {
    setPosts(next);
    try {
      const result = await window.storage.set("posts", JSON.stringify(next), false);
      if (!result) setStorageOk(false);
    } catch (e) {
      setStorageOk(false);
    }
  }, []);

  // ---- CSV import (post_log.csv from bot.py) ----
  const handleFile = useCallback((file) => {
    Papa.parse(file, {
      header: true,
      skipEmptyLines: true,
      complete: (results) => {
        const incoming = results.data.map((row) => ({
          id: `${row.timestamp}-${row.story_title}`,
          timestamp: row.timestamp,
          title: row.story_title,
          videoId: row.video_id || "",
          status: row.status,
          platform: row.video_id ? "youtube" : null,
          views: null,
          likes: null,
        }));
        setPosts((prev) => {
          const byId = new Map(prev.map((p) => [p.id, p]));
          incoming.forEach((p) => {
            if (byId.has(p.id)) {
              byId.set(p.id, { ...byId.get(p.id), ...p, views: byId.get(p.id).views, likes: byId.get(p.id).likes });
            } else {
              byId.set(p.id, p);
            }
          });
          const merged = Array.from(byId.values()).sort((a, b) =>
            new Date(b.timestamp) - new Date(a.timestamp)
          );
          persist(merged);
          return merged;
        });
      },
    });
  }, [persist]);

  const onDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) handleFile(file);
  };

  // ---- manual metric logging ----
  const saveMetrics = (id, platform, views, likes) => {
    const next = posts.map((p) =>
      p.id === id ? { ...p, platform, views: Number(views) || 0, likes: Number(likes) || 0 } : p
    );
    persist(next);
    setMetricForm(null);
  };

  // ---- derived stats ----
  const stats = useMemo(() => {
    const posted = posts.filter((p) => p.status === "posted" || p.status === "posted_manual").length;
    const pending = posts.filter((p) => p.status === "pending_review").length;
    const failed = posts.filter((p) => p.status === "upload_failed").length;
    const today = new Date().toISOString().slice(0, 10);
    const todayCount = posts.filter((p) => p.timestamp?.startsWith(today) &&
      (p.status === "posted" || p.status === "posted_manual")).length;
    const totalViews = posts.reduce((sum, p) => sum + (p.views || 0), 0);
    return { posted, pending, failed, total: posts.length, todayCount, totalViews };
  }, [posts]);

  const stageCounts = useMemo(() => ({
    trend: posts.length,
    story: posts.length,
    voice: posts.length,
    assemble: posts.length,
    review: stats.pending,
    post: stats.posted,
  }), [posts, stats]);

  const chartData = useMemo(() => {
    const byDay = {};
    posts.forEach((p) => {
      const day = p.timestamp?.slice(0, 10);
      if (!day) return;
      byDay[day] = byDay[day] || { day, posted: 0, pending: 0, failed: 0 };
      if (p.status === "posted" || p.status === "posted_manual") byDay[day].posted++;
      else if (p.status === "pending_review") byDay[day].pending++;
      else if (p.status === "upload_failed") byDay[day].failed++;
    });
    return Object.values(byDay).sort((a, b) => a.day.localeCompare(b.day));
  }, [posts]);

  const platformData = useMemo(() => {
    const byPlatform = {};
    posts.forEach((p) => {
      if (!p.platform || !p.views) return;
      byPlatform[p.platform] = (byPlatform[p.platform] || 0) + p.views;
    });
    return Object.entries(byPlatform).map(([platform, views]) => ({
      name: PLATFORM_META[platform]?.label || platform,
      value: views,
      color: PLATFORM_META[platform]?.color || C.muted,
    }));
  }, [posts]);

  return (
    <div style={{ minHeight: "100vh", background: C.bg, color: C.text, fontFamily: "system-ui, -apple-system, sans-serif" }}>
      <div style={{ maxWidth: 960, margin: "0 auto", padding: "20px 16px 60px" }}>

        {/* header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 24 }}>
          <div>
            <div style={{ fontSize: 11, letterSpacing: "0.12em", color: C.muted, textTransform: "uppercase", marginBottom: 4 }}>
              Media Maker
            </div>
            <h1 style={{ fontSize: 24, fontWeight: 700, letterSpacing: "-0.02em", margin: 0 }}>
              Ops Dashboard
            </h1>
          </div>
          <div style={{ textAlign: "right", fontFamily: "ui-monospace, monospace", fontSize: 12, color: C.muted }}>
            {stats.todayCount}/6 uploaded today
          </div>
        </div>

        {!storageOk && (
          <div style={{ background: C.surfaceAlt, border: `1px solid ${C.red}`, borderRadius: 8, padding: 12, marginBottom: 16, fontSize: 13, color: C.red }}>
            Couldn't save to storage -- data will reset on refresh this session.
          </div>
        )}

        {/* signature: pipeline flow */}
        <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 12, padding: "20px 16px", marginBottom: 20, overflowX: "auto" }}>
          <div style={{ display: "flex", alignItems: "center", minWidth: 560 }}>
            {STAGES.map((stage, i) => {
              const Icon = stage.icon;
              const isLast = i === STAGES.length - 1;
              const color = stage.key === "post" ? C.mint : stage.key === "review" ? C.amber : C.violet;
              return (
                <React.Fragment key={stage.key}>
                  <div style={{ display: "flex", flexDirection: "column", alignItems: "center", minWidth: 72 }}>
                    <div style={{
                      width: 40, height: 40, borderRadius: "50%", border: `1.5px solid ${color}`,
                      display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 8,
                    }}>
                      <Icon size={18} color={color} />
                    </div>
                    <div style={{ fontSize: 11, color: C.muted, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                      {stage.label}
                    </div>
                    <div style={{ fontFamily: "ui-monospace, monospace", fontSize: 15, fontWeight: 600, marginTop: 2 }}>
                      {stageCounts[stage.key]}
                    </div>
                  </div>
                  {!isLast && <div style={{ flex: 1, height: 1, background: C.border, margin: "0 4px 28px" }} />}
                </React.Fragment>
              );
            })}
          </div>
        </div>

        {/* stat cards */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))", gap: 10, marginBottom: 20 }}>
          {[
            { label: "Posted", value: stats.posted, color: C.mint, Icon: CheckCircle2 },
            { label: "Pending", value: stats.pending, color: C.amber, Icon: Clock },
            { label: "Failed", value: stats.failed, color: C.red, Icon: XCircle },
            { label: "Total views", value: stats.totalViews.toLocaleString(), color: C.violet, Icon: TrendingUp },
          ].map((card) => (
            <div key={card.label} style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 10, padding: 14 }}>
              <card.Icon size={16} color={card.color} style={{ marginBottom: 8 }} />
              <div style={{ fontFamily: "ui-monospace, monospace", fontSize: 20, fontWeight: 600 }}>{card.value}</div>
              <div style={{ fontSize: 11, color: C.muted, textTransform: "uppercase", letterSpacing: "0.04em" }}>{card.label}</div>
            </div>
          ))}
        </div>

        {/* charts */}
        {chartData.length > 0 && (
          <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 12, padding: 16, marginBottom: 20 }}>
            <div style={{ fontSize: 13, color: C.muted, marginBottom: 12 }}>Runs over time</div>
            <ResponsiveContainer width="100%" height={180}>
              <BarChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke={C.border} vertical={false} />
                <XAxis dataKey="day" stroke={C.muted} fontSize={11} tickLine={false} />
                <YAxis stroke={C.muted} fontSize={11} tickLine={false} allowDecimals={false} />
                <Tooltip contentStyle={{ background: C.surfaceAlt, border: `1px solid ${C.border}`, borderRadius: 8, fontSize: 12 }} />
                <Bar dataKey="posted" stackId="a" fill={C.mint} radius={[0, 0, 0, 0]} />
                <Bar dataKey="pending" stackId="a" fill={C.amber} />
                <Bar dataKey="failed" stackId="a" fill={C.red} radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}

        {platformData.length > 0 && (
          <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 12, padding: 16, marginBottom: 20, display: "flex", alignItems: "center", gap: 20 }}>
            <ResponsiveContainer width={140} height={140}>
              <PieChart>
                <Pie data={platformData} dataKey="value" nameKey="name" innerRadius={40} outerRadius={65} paddingAngle={3}>
                  {platformData.map((entry, i) => <Cell key={i} fill={entry.color} />)}
                </Pie>
              </PieChart>
            </ResponsiveContainer>
            <div>
              <div style={{ fontSize: 13, color: C.muted, marginBottom: 8 }}>Views by platform</div>
              {platformData.map((p) => (
                <div key={p.name} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, marginBottom: 4 }}>
                  <div style={{ width: 8, height: 8, borderRadius: "50%", background: p.color }} />
                  {p.name}: <span style={{ fontFamily: "ui-monospace, monospace" }}>{p.value.toLocaleString()}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* import */}
        <div
          onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
          style={{
            border: `1.5px dashed ${dragOver ? C.violet : C.border}`,
            borderRadius: 12, padding: 20, textAlign: "center", marginBottom: 20,
            background: dragOver ? C.surfaceAlt : "transparent", transition: "all 0.15s",
          }}
        >
          <Upload size={20} color={C.muted} style={{ marginBottom: 8 }} />
          <div style={{ fontSize: 13, color: C.muted, marginBottom: 10 }}>
            Drop your <span style={{ fontFamily: "ui-monospace, monospace" }}>output/post_log.csv</span> here to sync pipeline activity
          </div>
          <label style={{ fontSize: 12, color: C.violet, cursor: "pointer", border: `1px solid ${C.violet}`, borderRadius: 6, padding: "6px 12px", display: "inline-block" }}>
            Choose file
            <input type="file" accept=".csv" style={{ display: "none" }} onChange={(e) => e.target.files?.[0] && handleFile(e.target.files[0])} />
          </label>
        </div>

        {/* activity log */}
        <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 12, overflow: "hidden" }}>
          <div style={{ padding: "12px 16px", fontSize: 13, color: C.muted, borderBottom: `1px solid ${C.border}` }}>
            Activity log
          </div>
          {loading ? (
            <div style={{ padding: 24, textAlign: "center", color: C.muted, fontSize: 13 }}>Loading...</div>
          ) : posts.length === 0 ? (
            <div style={{ padding: 24, textAlign: "center", color: C.muted, fontSize: 13 }}>
              No runs logged yet. Drop in your post_log.csv, or run the bot to generate one.
            </div>
          ) : (
            posts.map((p) => (
              <div key={p.id} style={{ padding: "12px 16px", borderBottom: `1px solid ${C.border}`, display: "flex", alignItems: "center", gap: 12 }}>
                <div style={{ width: 8, height: 8, borderRadius: "50%", background: statusColor(p.status), flexShrink: 0 }} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {p.title?.replace(/_/g, " ") || "untitled"}
                  </div>
                  <div style={{ fontSize: 11, color: C.muted, fontFamily: "ui-monospace, monospace" }}>
                    {p.timestamp?.slice(0, 16).replace("T", " ")} · {statusLabel(p.status)}
                    {p.views != null && ` · ${p.views.toLocaleString()} views`}
                  </div>
                </div>
                <button
                  onClick={() => setMetricForm(metricForm?.id === p.id ? null : { id: p.id })}
                  style={{ background: "none", border: `1px solid ${C.border}`, borderRadius: 6, color: C.muted, fontSize: 11, padding: "4px 8px", cursor: "pointer", flexShrink: 0 }}
                >
                  {p.views != null ? "Edit" : "Add views"}
                </button>
              </div>
            ))
          )}
        </div>

        {metricForm && (
          <MetricForm
            post={posts.find((p) => p.id === metricForm.id)}
            onSave={saveMetrics}
            onCancel={() => setMetricForm(null)}
            colors={C}
          />
        )}

        <div style={{ fontSize: 11, color: C.muted, textAlign: "center", marginTop: 24 }}>
          View/like counts are entered manually for now -- connect Supermetrics for automatic cross-platform sync.
        </div>
      </div>
    </div>
  );
}

function MetricForm({ post, onSave, onCancel, colors: C }) {
  const [platform, setPlatform] = useState(post?.platform || "youtube");
  const [views, setViews] = useState(post?.views ?? "");
  const [likes, setLikes] = useState(post?.likes ?? "");

  if (!post) return null;

  return (
    <div style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)",
      display: "flex", alignItems: "flex-end", justifyContent: "center", zIndex: 50,
    }} onClick={onCancel}>
      <div
        onClick={(e) => e.stopPropagation()}
        style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: "16px 16px 0 0", padding: 20, width: "100%", maxWidth: 480 }}
      >
        <div style={{ fontSize: 14, marginBottom: 14, color: C.text }}>
          {post.title?.replace(/_/g, " ")}
        </div>

        <div style={{ display: "flex", gap: 8, marginBottom: 14 }}>
          {Object.entries(PLATFORM_META).map(([key, meta]) => (
            <button
              key={key}
              onClick={() => setPlatform(key)}
              style={{
                flex: 1, padding: "8px 0", borderRadius: 8, fontSize: 12,
                border: `1px solid ${platform === key ? meta.color : C.border}`,
                background: platform === key ? `${meta.color}22` : "transparent",
                color: platform === key ? meta.color : C.muted, cursor: "pointer",
              }}
            >
              {meta.label}
            </button>
          ))}
        </div>

        <div style={{ display: "flex", gap: 10, marginBottom: 16 }}>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 11, color: C.muted, marginBottom: 4 }}>Views</div>
            <input
              type="number" value={views} onChange={(e) => setViews(e.target.value)}
              style={{ width: "100%", background: C.surfaceAlt, border: `1px solid ${C.border}`, borderRadius: 6, padding: 8, color: C.text, fontFamily: "ui-monospace, monospace" }}
            />
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 11, color: C.muted, marginBottom: 4 }}>Likes</div>
            <input
              type="number" value={likes} onChange={(e) => setLikes(e.target.value)}
              style={{ width: "100%", background: C.surfaceAlt, border: `1px solid ${C.border}`, borderRadius: 6, padding: 8, color: C.text, fontFamily: "ui-monospace, monospace" }}
            />
          </div>
        </div>

        <div style={{ display: "flex", gap: 8 }}>
          <button onClick={onCancel} style={{ flex: 1, padding: 10, borderRadius: 8, border: `1px solid ${C.border}`, background: "none", color: C.muted, cursor: "pointer" }}>
            Cancel
          </button>
          <button
            onClick={() => onSave(post.id, platform, views, likes)}
            style={{ flex: 1, padding: 10, borderRadius: 8, border: "none", background: C.mint, color: "#0D1017", fontWeight: 600, cursor: "pointer" }}
          >
            Save
          </button>
        </div>
      </div>
    </div>
  );
}
