"""
gen_dashboard.py
Regenerates dashboard/live.html -- a full multi-tab ops dashboard with the
latest stats baked in. The hourly bot runs this after channel_stats.py, so
the page is always current when opened.

Tabs: Overview (aggregate + growth), YouTube (per-video, real API data),
Instagram (manual entry -- no auto feed yet), Revenue (actual $0 pre-YPP +
estimated). Growth charts fill in over time via dashboard/history.json.

Reads:  output/channel_stats.json, output/post_log.csv
Writes: dashboard/live.html, dashboard/history.json (append-only snapshots)
"""

import csv
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
STATS = ROOT / "output" / "channel_stats.json"
IG_STATS = ROOT / "output" / "ig_stats.json"
POST_LOG = ROOT / "output" / "post_log.csv"
HIST = ROOT / "dashboard" / "history.json"
OUT = ROOT / "dashboard" / "live.html"

RPM = 0.10            # $ per 1k Shorts views (typical midpoint)
YPP_SUBS = 1000
YPP_VIEWS_90D = 10_000_000


def _load_posts():
    posts = []
    if not POST_LOG.exists():
        return posts
    with open(POST_LOG) as f:
        for row in csv.reader(f):
            if len(row) >= 4 and row[3] in ("posted", "posted_manual"):
                posts.append({"date": row[0][:10], "title": row[1], "videoId": row[2]})
    return posts


def _update_history(total_views, subs, fetched, ig_views=0):
    """Snapshot per-platform views so the chart can show a real all-platforms
    total. Older rows only have `views` (YouTube), so `yt`/`ig` are stored
    alongside it and the chart falls back to `views` for those."""
    hist = json.loads(HIST.read_text()) if HIST.exists() else []
    if not hist or hist[-1].get("t") != fetched:
        hist.append({"t": fetched, "views": total_views + ig_views,
                     "yt": total_views, "ig": ig_views, "subs": subs})
    hist = hist[-500:]
    HIST.parent.mkdir(parents=True, exist_ok=True)
    HIST.write_text(json.dumps(hist))
    return hist


def build():
    if not STATS.exists():
        print("No channel_stats.json yet -- run channel_stats.py first.")
        return
    s = json.loads(STATS.read_text())
    vids = sorted(s.get("videos", []), key=lambda v: v["views"], reverse=True)
    total_views = sum(v["views"] for v in vids)
    total_likes = sum(v["likes"] for v in vids)
    total_comments = sum(v.get("comments", 0) for v in vids)
    fetched = s.get("fetchedAt", "")
    # load IG first so the history snapshot can record both platforms
    ig = json.loads(IG_STATS.read_text()) if IG_STATS.exists() else {"totalViews": 0, "media": []}
    hist = _update_history(total_views, s.get("subscribers", 0), fetched,
                           ig_views=ig.get("totalViews", 0))

    # TikTok drafts waiting on the production audit -- counted, not linked,
    # since sandbox posts aren't publicly viewable yet.
    tt_q = ROOT / "output" / "tiktok_queue.json"
    try:
        tt_rows = json.loads(tt_q.read_text(encoding="utf-8"))
    except Exception:
        tt_rows = []
    tt_drafts = sum(1 for r in tt_rows if r.get("status") == "posted")
    tt_queue = [{"title": r.get("title", ""), "status": r.get("status", ""),
                 "when": r.get("queued", "")} for r in tt_rows][-40:]

    data = {
        "ttDrafts": tt_drafts,
        "ttQueue": tt_queue,
        "channel": s.get("channel", "channel"),
        "subs": s.get("subscribers", 0),
        "totalViews": total_views,
        "totalLikes": total_likes,
        "totalComments": total_comments,
        "count": len(vids),
        "fetched": fetched,
        "videos": vids,
        "history": hist,
        "ig": ig,
        "posts": _load_posts(),
        "rpm": RPM,
        "yppSubs": YPP_SUBS,
        "yppViews": YPP_VIEWS_90D,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(_TEMPLATE.replace("/*DATA*/", json.dumps(data)), encoding="utf-8")
    print(f"Live dashboard -> {OUT}  ({total_views} views, {len(vids)} videos, {len(hist)} history pts)")


_TEMPLATE = r"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ParkourFlux — Ops</title>
<style>
:root{--bg:#0D1017;--surface:#161B26;--alt:#1E2432;--border:#2A3142;--text:#E9EAEE;--muted:#8890A3;--mint:#5EE6B9;--violet:#7C8CFF;--amber:#F0B429;--red:#F0553D;--pink:#E85D9B;--bgGrad:linear-gradient(150deg,#241C52 0%,#0F1119 46%,#0C1C38 100%)}
@media(prefers-color-scheme:light){:root{--bg:#F2F3F7;--surface:#fff;--alt:#E9EBF2;--border:#D4D8E3;--text:#1A1E2A;--muted:#6A7186;--violet:#5163E0;--mint:#0FA97C;--bgGrad:linear-gradient(150deg,#ECE7FB 0%,#F2F3F7 52%,#E4EDFB 100%)}}
*{box-sizing:border-box}body{margin:0;background:var(--bgGrad);background-attachment:fixed;color:var(--text);font-family:system-ui,-apple-system,"Segoe UI",sans-serif;font-size:14px}
.app{display:flex;min-height:100vh}
.side{width:190px;flex-shrink:0;border-right:1px solid var(--border);padding:20px 12px;position:sticky;top:0;height:100vh}
.brand{font-size:12px;letter-spacing:.1em;color:var(--muted);text-transform:uppercase;padding:0 8px 16px}
.nav{display:flex;flex-direction:column;gap:4px}
.nav button{display:flex;align-items:center;gap:10px;text-align:left;background:none;border:none;color:var(--muted);font-size:14px;padding:10px 12px;border-radius:8px;cursor:pointer;width:100%}
.nav button:hover{background:var(--alt)}.nav button.on{background:var(--alt);color:var(--text);font-weight:600}
.nav .ic{width:8px;height:8px;border-radius:50%;background:currentColor;opacity:.7}
.main{flex:1;padding:28px 28px 60px;max-width:900px}
h1{font-size:22px;margin:0 0 4px}.sub{color:var(--muted);font-size:12px;margin-bottom:22px;display:flex;align-items:center;gap:6px}
.dot{width:7px;height:7px;border-radius:50%;background:var(--mint);animation:p 2s infinite}@keyframes p{0%,100%{opacity:1}50%{opacity:.3}}
.tab{display:none}.tab.on{display:block}
.hero{background:var(--surface);border:1px solid var(--border);border-radius:16px;padding:28px;text-align:center;margin-bottom:14px}
.hero .n{font-size:56px;font-weight:750;letter-spacing:-.02em;font-variant-numeric:tabular-nums;line-height:1;color:var(--violet)}
.hero .l{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;margin-top:8px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin-bottom:14px}
.tile{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:15px}
.tile .v{font-size:22px;font-weight:650;font-variant-numeric:tabular-nums}.tile .l{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;margin-top:4px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:16px;margin-bottom:14px}
.ct{font-size:13px;color:var(--muted);margin-bottom:12px}
.scroll{overflow-x:auto}
.row{display:flex;align-items:center;gap:12px;padding:10px 0;border-bottom:1px solid var(--border)}.row:last-child{border:none}
.rank{color:var(--muted);width:18px;font-variant-numeric:tabular-nums}
.rtitle{flex:1;font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.rtitle a{color:var(--text);text-decoration:none}
.rv{font-variant-numeric:tabular-nums;font-weight:600}.rv .s{color:var(--muted);font-weight:400;font-size:12px;margin-left:8px}
.feat{display:flex;align-items:center;gap:16px}.feat .big{font-size:32px;font-weight:700;color:var(--mint);font-variant-numeric:tabular-nums}
.pill{display:inline-block;font-size:10px;padding:2px 8px;border-radius:99px;border:1px solid var(--border);color:var(--muted)}
.bar{height:8px;background:var(--alt);border-radius:99px;overflow:hidden;margin:6px 0}.bar > i{display:block;height:100%;background:var(--violet);border-radius:99px}
input.mv{width:70px;background:var(--alt);border:1px solid var(--border);border-radius:6px;color:var(--text);padding:4px 6px;font-variant-numeric:tabular-nums}
svg text{fill:var(--muted)}
footer{color:var(--muted);font-size:11px;margin-top:20px}
.note{font-size:11px;color:var(--muted);margin-top:8px}
/* metric cards */
.st{display:inline-block;font-size:9.5px;font-weight:700;letter-spacing:.06em;
    padding:2px 7px;border-radius:5px;vertical-align:middle;margin-left:6px;white-space:nowrap}
.st.live{background:rgba(62,207,142,.14);color:var(--mint)}
.st.sched{background:rgba(245,180,60,.14);color:var(--amber)}
.st.skip{background:rgba(140,148,170,.14);color:var(--muted)}
.libcard{margin-bottom:16px}
.counters{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px}
.ctr{position:relative;padding:4px 0 4px 16px;border-left:3px solid var(--violet)}
.ctr:nth-child(2){border-left-color:var(--amber)}
.ctr:nth-child(3){border-left-color:var(--mint)}
.ctr:nth-child(4){border-left-color:var(--pink)}
.ctr .cn{font-size:34px;font-weight:700;line-height:1.05;font-variant-numeric:tabular-nums}
.ctr .cn.sched{color:var(--amber)}
.ctr .cl{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin-top:3px}
.ctr .cs{font-size:12px;color:var(--muted);margin-top:5px;opacity:.85}
.upnext{margin-top:16px;border-top:1px solid var(--border);padding-top:12px;display:grid;gap:7px}
.un{display:flex;align-items:center;gap:10px;font-size:12.5px}
.un .when{color:var(--amber);font-variant-numeric:tabular-nums;white-space:nowrap;min-width:118px}
.un .tt{color:var(--text);opacity:.9;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.un .live{color:var(--mint)}
.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));gap:12px;margin-bottom:16px}
.mcard{background:var(--surface);border:1px solid var(--border);border-radius:16px;padding:16px;display:flex;align-items:center;gap:13px}
.mcard .badge{width:44px;height:44px;border-radius:13px;display:flex;align-items:center;justify-content:center;font-size:19px;flex-shrink:0;color:#fff;box-shadow:0 4px 14px -4px rgba(0,0,0,.5)}
.b-views{background:linear-gradient(135deg,#E85D9B,#A855F7)}.b-likes{background:linear-gradient(135deg,#F0553D,#F97362)}
.b-cmts{background:linear-gradient(135deg,#F0B429,#F5CB5B)}.b-shares{background:linear-gradient(135deg,#3ECF8E,#22B8A6)}
.b-eng{background:linear-gradient(135deg,#5B8DEF,#7C8CFF)}
.mcard .ml{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
.mcard .mv{font-size:25px;font-weight:730;font-variant-numeric:tabular-nums;line-height:1.15;letter-spacing:-.01em}
/* chart header + toggle */
.charthead{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;margin-bottom:14px}
.chartctl{display:flex;gap:8px;align-items:center}
.toggle{display:inline-flex;background:var(--alt);border-radius:9px;padding:3px}
.toggle button{background:none;border:none;color:var(--muted);font-size:12px;padding:5px 13px;border-radius:6px;cursor:pointer;font-weight:500}
.toggle button.on{background:var(--violet);color:#fff;font-weight:600}
select.range{background:var(--alt);border:1px solid var(--border);color:var(--text);border-radius:8px;padding:6px 10px;font-size:12px;cursor:pointer}
/* thumbnail row */
.thumbs{display:flex;gap:13px;overflow-x:auto;padding-bottom:6px}
.thumb{flex-shrink:0;width:116px;text-decoration:none}
.thumb .imgwrap{position:relative;width:116px;height:206px;border-radius:13px;overflow:hidden;border:1px solid var(--border);background:var(--alt)}
.thumb img{width:100%;height:100%;object-fit:cover;display:block}
.thumb .ov{position:absolute;left:0;right:0;bottom:0;padding:14px 8px 7px;background:linear-gradient(transparent,rgba(0,0,0,.82));color:#fff;font-size:12px;font-weight:700;font-variant-numeric:tabular-nums}
.thumb .tl{font-size:10px;color:var(--muted);margin-top:5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
</style></head><body>
<div class="app">
 <aside class="side"><div class="brand">ParkourFlux</div><nav class="nav" id="nav">
  <button data-t="overview" class="on"><span class="ic" style="color:var(--violet)"></span>Overview</button>
  <button data-t="youtube"><span class="ic" style="color:var(--red)"></span>YouTube</button>
  <button data-t="instagram"><span class="ic" style="color:var(--pink)"></span>Instagram</button>
  <button data-t="tiktok"><span class="ic" style="color:var(--amber)"></span>TikTok</button>
  <button data-t="revenue"><span class="ic" style="color:var(--mint)"></span>Revenue</button>
  <button data-t="assistant"><span class="ic" style="color:var(--mint)"></span>Assistant</button>
 </nav></aside>
 <main class="main">
  <h1 id="ch"></h1><div class="sub"><span class="dot"></span><span id="sync"></span></div>

  <section class="tab on" data-t="overview">
   <div class="card libcard">
    <div class="ct" style="margin:0 0 14px">Library — what's out there right now</div>
    <div class="counters">
     <div class="ctr"><div class="cn" id="cLive">0</div><div class="cl">Live now</div>
       <div class="cs"><span id="cYT">0</span> YouTube · <span id="cIG">0</span> Instagram</div></div>
     <div class="ctr"><div class="cn sched" id="cSched">0</div><div class="cl">Scheduled</div>
       <div class="cs" id="cNext">—</div></div>
     <div class="ctr"><div class="cn" id="cStories">0</div><div class="cl">Stories made</div>
       <div class="cs" id="cWeek">— this week</div></div>
     <div class="ctr"><div class="cn" id="cTT">0</div><div class="cl">TikTok drafts</div>
       <div class="cs">awaiting audit</div></div>
    </div>
    <div class="upnext" id="upNext"></div>
   </div>
   <div class="metrics">
    <div class="mcard"><div class="badge b-views">👁</div><div><div class="ml">Views</div><div class="mv" id="mViews">0</div></div></div>
    <div class="mcard"><div class="badge b-likes">♥</div><div><div class="ml">Likes</div><div class="mv" id="mLikes">0</div></div></div>
    <div class="mcard"><div class="badge b-cmts">💬</div><div><div class="ml">Comments</div><div class="mv" id="mCmts">0</div></div></div>
    <div class="mcard"><div class="badge b-shares">↗</div><div><div class="ml">Shares</div><div class="mv" id="mShares">0</div></div></div>
    <div class="mcard"><div class="badge b-eng">📈</div><div><div class="ml">Engagement</div><div class="mv" id="mEng">0%</div></div></div>
   </div>
   <div class="card">
    <div class="charthead">
     <div class="ct" style="margin:0" id="chartTitle">Views · all platforms</div>
     <div class="chartctl">
      <select class="range" id="platSel"><option value="all" selected>All platforms</option><option value="yt">YouTube</option><option value="ig">Instagram</option></select>
      <div class="toggle"><button id="tgCumul" class="on">Cumulative</button><button id="tgDelta">Delta</button></div>
      <select class="range" id="rangeSel"><option value="1">Last 24 hours</option><option value="3">Last 3 days</option><option value="7">Last 7 days</option><option value="30">Last 30 days</option><option value="0" selected>All time</option></select>
     </div>
    </div>
    <div class="scroll" id="cViews"></div><div class="note" id="viewsNote"></div>
   </div>
   <div class="card"><div class="ct">Recent posts</div><div class="thumbs" id="thumbs"></div></div>
   <div class="card"><div class="ct">🏆 Most-viewed video (all platforms)</div><div class="feat" id="feat"></div></div>
   <div class="card"><div class="ct">Posting activity (videos/day)</div><div class="scroll" id="cPosts"></div></div>
  </section>

  <section class="tab" data-t="youtube">
   <div class="tiles">
    <div class="tile"><div class="v" id="ytv">0</div><div class="l">YouTube views</div></div>
    <div class="tile"><div class="v" id="ysubs">0</div><div class="l">Subscribers</div></div>
    <div class="tile"><div class="v" id="ycnt">0</div><div class="l">Videos live</div></div></div>
   <div class="card"><div class="ct">Subscribers over time</div><div class="scroll" id="cSubs"></div></div>
   <div class="card"><div class="ct">Views per video</div><div class="scroll" id="cPerVid"></div></div>
   <div class="card"><div class="ct">All videos</div><div id="ytList"></div></div>
  </section>

  <section class="tab" data-t="instagram">
   <div class="tiles">
    <div class="tile"><div class="v" id="igv">0</div><div class="l">IG views (live)</div></div>
    <div class="tile"><div class="v" id="iglk">0</div><div class="l">Likes</div></div>
    <div class="tile"><div class="v" id="igcnt">0</div><div class="l">Posts</div></div></div>
   <div class="card"><div class="ct">Your Instagram posts (auto — pulled from the IG API)</div>
    <div id="igList"></div>
    <div class="note" id="igNote"></div></div>
  </section>

  <section class="tab" data-t="tiktok">
   <div class="tiles">
    <div class="tile"><div class="v" id="ttv">0</div><div class="l">TikTok views (manual)</div></div>
    <div class="tile"><div class="v" id="ttcnt">0</div><div class="l">Posts tracked</div></div></div>
   <div class="card"><div class="ct">Connection status</div>
    <div class="feat"><div><div><span class="pill">Connected · draft mode</span></div>
     <div class="note" style="margin-top:8px">Authorized 22 Jul 2026 — the pipeline can push any rendered video
     straight to your TikTok drafts (ask the bot: <em>“push the last 2 videos to TikTok”</em>, or run
     <code>tiktok_upload.py post-latest</code>). Uploads land in the TikTok app under Inbox/drafts and
     <strong>you tap Post</strong> — TikTok's sandbox doesn't allow fully public auto-posting until the app
     passes their production audit, so TikTok sits outside the automatic 2-a-day cadence for now.</div></div></div></div>
   <div class="card"><div class="ct">Pushed to TikTok</div>
    <div id="ttPushed"></div></div>
   <div class="card"><div class="ct">Manual view tracking — type each TikTok's views (saved in this browser)</div>
    <div id="ttList"></div>
    <div class="note">No auto stats feed yet (that needs the production audit too). Enter numbers from the app; they feed the "all platforms" totals.</div></div>
  </section>

  <section class="tab" data-t="revenue">
   <div class="tiles">
    <div class="tile"><div class="v" style="color:var(--mint)" id="ract">$0.00</div><div class="l">Actual revenue</div></div>
    <div class="tile"><div class="v" id="rest">$0</div><div class="l">Est. earned value</div></div>
    <div class="tile"><div class="v" id="rmo">$0</div><div class="l">Est. /mo at pace</div></div></div>
   <div class="card"><div class="ct">Path to monetization (YouTube Partner Program)</div>
    <div style="margin-bottom:14px"><div style="display:flex;justify-content:space-between;font-size:13px"><span>Subscribers</span><span id="subProg" class="rv"></span></div><div class="bar"><i id="subBar"></i></div></div>
    <div><div style="display:flex;justify-content:space-between;font-size:13px"><span>Views (toward 10M/90d)</span><span id="viewProg" class="rv"></span></div><div class="bar"><i id="viewBar" style="background:var(--amber)"></i></div></div>
    <div class="note">Actual revenue is $0 until you hit YPP (1,000 subs + 10M Shorts views/90d). Estimate applies a $0.10/1k Shorts RPM to current views — what today's views would be worth once monetized.</div></div>
  </section>
  <section class="tab" data-t="assistant">
   <div class="card" style="display:flex;align-items:center;justify-content:space-between">
    <div><div style="font-weight:600">Autonomous mode</div><div class="note" id="autoState">checking…</div></div>
    <label style="position:relative;display:inline-block;width:48px;height:26px">
     <input type="checkbox" id="autoTog" style="opacity:0;width:0;height:0">
     <span id="autoSlide" style="position:absolute;inset:0;background:var(--border);border-radius:99px;transition:.2s;cursor:pointer"></span>
     <span id="autoKnob" style="position:absolute;left:3px;top:3px;width:20px;height:20px;background:#fff;border-radius:50%;transition:.2s"></span></label>
   </div>
   <div class="card">
    <div class="ct">Ask the bot anything — check stats, post a video, or run it</div>
    <div id="chat" style="min-height:220px;max-height:360px;overflow-y:auto;display:flex;flex-direction:column;gap:10px;margin-bottom:12px"></div>
    <div id="chips" style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px"></div>
    <div style="display:flex;gap:8px">
     <button id="cattach" title="Attach a file" style="background:var(--alt);border:1px solid var(--border);color:var(--text);border-radius:8px;padding:0 14px;font-size:16px;cursor:pointer">📎</button>
     <input type="file" id="cfile" multiple style="display:none">
     <input id="cin" placeholder="e.g. how are we doing? / post a scary story / drop a file" style="flex:1;background:var(--alt);border:1px solid var(--border);border-radius:8px;color:var(--text);padding:10px 12px">
     <button id="csend" style="background:var(--violet);border:none;color:#fff;border-radius:8px;padding:0 18px;font-weight:600;cursor:pointer">Send</button></div>
    <div class="note" style="margin-top:10px">Attach or drag-drop files: images (it sees them) · mp4 footage / mp3 music (it files them) · text (it reads them)</div>
   </div>
  </section>
  <footer>Auto-refreshes every 5 min · regenerated hourly by the bot · YouTube + Instagram = live API · TikTok = drafts, manual stats</footer>
 </main></div>
<script>
const D=/*DATA*/;const $=id=>document.getElementById(id);
const fmt=n=>n>=1e6?(n/1e6).toFixed(1).replace(/\.0$/,'')+'M':n>=1e3?(n/1e3).toFixed(1).replace(/\.0$/,'')+'K':Math.round(n).toLocaleString();
const money=n=>'$'+(n<100?n.toFixed(2):Math.round(n).toLocaleString());

// ---- manual IG views (localStorage) ----
const IG=D.ig||{totalViews:0,media:[]};
const TTK='pf_tt_views';let tt={};try{tt=JSON.parse(localStorage.getItem(TTK)||'{}')}catch(e){}
function ttTotal(){return Object.values(tt).reduce((a,b)=>a+(+b||0),0)}

// ---- tabs ----
$('nav').addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;
 document.querySelectorAll('.nav button').forEach(x=>x.classList.toggle('on',x===b));
 document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('on',t.dataset.t===b.dataset.t));});

// ---- header ----
$('ch').textContent=D.channel;
const f=D.fetched?new Date(D.fetched):null;
function ago(){if(!f){$('sync').textContent='no sync yet';return}const m=Math.round((Date.now()-f)/60000);
 $('sync').textContent=m<1?'synced just now':m<60?'synced '+m+' min ago':'synced '+Math.round(m/60)+'h ago'}
ago();setInterval(ago,30000);

// ---- charts (inline SVG, no libs) ----
function line(el,pts,color){if(pts.length<2){el.innerHTML='<div class="note">Not enough history yet — fills in over the next few hours.</div>';return}
 const W=820,H=170,pl=44,pb=22,pt=10;const xs=pts.map(p=>p.x),ys=pts.map(p=>p.y);
 const x0=Math.min(...xs),x1=Math.max(...xs),ymax=Math.max(...ys,1)*1.15;
 const X=v=>pl+(W-pl-14)*(x1===x0?.5:(v-x0)/(x1-x0)),Y=v=>pt+(H-pt-pb)*(1-v/ymax);
 let g='';for(let i=1;i<=3;i++){const y=pt+(H-pt-pb)*i/4;g+=`<line x1="${pl}" y1="${y}" x2="${W-10}" y2="${y}" stroke="var(--border)" stroke-dasharray="2 4"/><text x="${pl-6}" y="${y+4}" text-anchor="end" font-size="10">${fmt(ymax*(1-i/4))}</text>`}
 let d='';pts.forEach((p,i)=>d+=(i?'L':'M')+X(p.x).toFixed(1)+' '+Y(p.y).toFixed(1));
 const last=pts[pts.length-1];
 el.innerHTML=`<svg viewBox="0 0 ${W} ${H}" width="100%" style="min-width:560px">${g}<path d="${d}" fill="none" stroke="${color}" stroke-width="2"/><circle cx="${X(last.x)}" cy="${Y(last.y)}" r="4" fill="${color}"/><text x="${W-12}" y="${Y(last.y)-8}" text-anchor="end" font-size="11" font-weight="600" fill="var(--text)">${fmt(last.y)}</text></svg>`}
function bars(el,items,color){if(!items.length){el.innerHTML='<div class="note">No data yet.</div>';return}
 const W=820,rowH=26,pad=6;const max=Math.max(...items.map(i=>i.v),1);const H=items.length*rowH+pad*2;
 let s=`<svg viewBox="0 0 ${W} ${H}" width="100%" style="min-width:520px">`;
 items.forEach((it,i)=>{const y=pad+i*rowH;const w=(W-220)*it.v/max;
  s+=`<text x="0" y="${y+15}" font-size="11" fill="var(--text)">${it.label.slice(0,26)}</text><rect x="180" y="${y+4}" width="${Math.max(w,2)}" height="14" rx="4" fill="${color}"/><text x="${180+Math.max(w,2)+6}" y="${y+15}" font-size="11" font-weight="600" fill="var(--text)">${fmt(it.v)}</text>`});
 el.innerHTML=s+'</svg>'}
// gradient area chart (the polished views line)
function area(el,pts,color){if(pts.length<2){el.innerHTML='<div class="note">Chart fills in as snapshots accumulate (saved hourly).</div>';return}
 const W=820,H=210,pl=46,pb=24,ptp=12;const xs=pts.map(p=>p.x),ys=pts.map(p=>p.y);
 const x0=Math.min(...xs),x1=Math.max(...xs),ymax=Math.max(...ys,1)*1.15;
 const X=v=>pl+(W-pl-16)*(x1===x0?.5:(v-x0)/(x1-x0)),Y=v=>ptp+(H-ptp-pb)*(1-v/ymax);
 let g='';for(let i=1;i<=4;i++){const y=ptp+(H-ptp-pb)*i/5;g+=`<line x1="${pl}" y1="${y}" x2="${W-12}" y2="${y}" stroke="var(--border)" stroke-dasharray="2 5"/><text x="${pl-8}" y="${y+4}" text-anchor="end" font-size="10">${fmt(ymax*(1-i/5))}</text>`}
 let d='';pts.forEach((p,i)=>d+=(i?'L':'M')+X(p.x).toFixed(1)+' '+Y(p.y).toFixed(1));
 const fill=d+`L${X(x1).toFixed(1)} ${Y(0).toFixed(1)}L${X(x0).toFixed(1)} ${Y(0).toFixed(1)}Z`;
 const last=pts[pts.length-1],gid='g'+Math.random().toString(36).slice(2,7);
 el.innerHTML=`<svg viewBox="0 0 ${W} ${H}" width="100%" style="min-width:560px"><defs><linearGradient id="${gid}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${color}" stop-opacity=".34"/><stop offset="1" stop-color="${color}" stop-opacity="0"/></linearGradient></defs>${g}<path d="${fill}" fill="url(#${gid})"/><path d="${d}" fill="none" stroke="${color}" stroke-width="2.4" stroke-linejoin="round"/><circle cx="${X(last.x)}" cy="${Y(last.y)}" r="4.5" fill="${color}"/><text x="${W-14}" y="${Y(last.y)-9}" text-anchor="end" font-size="12" font-weight="700" fill="var(--text)">${fmt(last.y)}</text></svg>`}
let chartMode='cumul',chartRange=0,chartPlat='all';
// Pull one platform's views out of a history row. Rows written before
// per-platform tracking only have `views` (YouTube-only), so fall back to it
// for yt and treat ig as 0 rather than dropping those points from the chart.
function seriesValue(row,plat){
 const yt=row.yt!==undefined?row.yt:(row.views||0);
 const ig=row.ig!==undefined?row.ig:0;
 return plat==='yt'?yt:plat==='ig'?ig:yt+ig;
}
const PLAT_LABEL={all:'all platforms',yt:'YouTube',ig:'Instagram'};
const PLAT_COLOR={all:'var(--mint)',yt:'var(--red)',ig:'var(--pink)'};
function drawViewsChart(){let h=D.history.slice();
 if(chartRange){const cut=Date.now()-chartRange*864e5;h=h.filter(x=>new Date(x.t).getTime()>=cut)}
 let pts;if(chartMode==='delta'){pts=[];for(let i=1;i<h.length;i++)pts.push({x:new Date(h[i].t).getTime(),y:Math.max(0,seriesValue(h[i],chartPlat)-seriesValue(h[i-1],chartPlat))})}
 else pts=h.map(x=>({x:new Date(x.t).getTime(),y:seriesValue(x,chartPlat)}));
 area($('cViews'),pts,PLAT_COLOR[chartPlat]||'var(--mint)');
 const lbl=PLAT_LABEL[chartPlat]||'all platforms';
 $('chartTitle').textContent='Views · '+lbl;
 // Show the real date span, not just a count -- with only a few days of
 // history the wider ranges all render the same chart, and without this the
 // dropdown looks broken when it is actually working.
 let note='';
 if(D.history.length<2){note='Not enough history yet — the chart fills in as the bot runs.'}
 else if(h.length<2){note='No snapshots in this range. Try a wider one.'}
 else{
  const a=new Date(h[0].t),b=new Date(h[h.length-1].t);
  const fmtd=d=>d.toLocaleDateString([],{month:'short',day:'numeric'})+' '+d.toLocaleTimeString([],{hour:'numeric'});
  const total=D.history.length;
  note=`${h.length} of ${total} snapshots · ${fmtd(a)} → ${fmtd(b)} · `+
       (chartMode==='delta'?lbl+' views gained per snapshot':'cumulative '+lbl+' views');
 }
 $('viewsNote').textContent=note}
function renderThumbs(){const seen=new Set(),items=[];
 for(let i=D.posts.length-1;i>=0&&items.length<12;i--){const p=D.posts[i];if(!p.videoId||seen.has(p.videoId))continue;seen.add(p.videoId);
  const v=D.videos.find(x=>x.videoId===p.videoId);items.push({id:p.videoId,title:p.title,views:v?v.views:0})}
 $('thumbs').innerHTML=items.length?items.map(it=>`<a class="thumb" href="https://youtube.com/watch?v=${it.id}" target="_blank"><div class="imgwrap"><img loading="lazy" src="https://i.ytimg.com/vi/${it.id}/hqdefault.jpg" onerror="this.style.opacity=.15"><div class="ov">${fmt(it.views)} views</div></div><div class="tl">${it.title}</div></a>`).join(''):'<div class="note">No posts yet.</div>'}

// ---- library counter: what is actually out there right now ----
// A video can be uploaded but not yet visible (private + publishAt), so
// "on the channel" and "live" are different numbers. Show both.
function renderLibrary(){
 const vids=D.videos||[];
 // Three states, not two: public = live, publishAt set = scheduled, and
 // unlisted/private with NO publishAt = hidden (a manual upload, e.g. a
 // compilation parked for review). Treating hidden as "scheduled" printed
 // "Invalid Date" because there's no date to format.
 const isSched=v=>!!v.publishAt;
 const isHidden=v=>!v.publishAt&&v.privacy&&v.privacy!=='public';
 const sched=vids.filter(isSched);
 const hidden=vids.filter(isHidden);
 const liveYT=vids.filter(v=>!isSched(v)&&!isHidden(v)).length;
 const liveIG=(IG.media||[]).length;
 $('cYT').textContent=liveYT;
 $('cIG').textContent=liveIG;
 $('cLive').textContent=liveYT+liveIG;
 $('cSched').textContent=sched.length+hidden.length;
 $('cTT').textContent=D.ttDrafts||0;
 // distinct stories = base titles, so a saga counts once
 const posts=D.posts||[];
 const base=s=>String(s||'').replace(/\.mp4$/,'').replace(/_pt\d+$/,'');
 const stories=new Set(posts.map(p=>base(p.title||p.story||p[1])));
 $('cStories').textContent=stories.size||vids.length;
 const wk=Date.now()-7*864e5;
 const recent=posts.filter(p=>{const t=Date.parse(p.when||p.t||p[0]);return t&&t>=wk;});
 const rs=new Set(recent.map(p=>base(p.title||p.story||p[1])));
 $('cWeek').textContent=(rs.size||0)+' this week';
 // upcoming releases, soonest first
 const up=sched.slice().sort((a,b)=>String(a.publishAt).localeCompare(String(b.publishAt)));
 $('cNext').textContent=up.length?('next '+new Date(up[0].publishAt).toLocaleDateString([],{weekday:'short'})):'none queued';
 // Scheduled rows show their release time; hidden rows show why they're not
 // live instead of a date they don't have.
 const rows=up.map(v=>{
   const d=new Date(v.publishAt);
   const when=isNaN(d)?'—':d.toLocaleDateString([],{weekday:'short',month:'short',day:'numeric'})+' '+
              d.toLocaleTimeString([],{hour:'numeric',minute:'2-digit'});
   return `<div class="un"><span class="when">${when}</span>`+
          `<span class="tt">${v.title||''}</span></div>`;
 }).concat(hidden.map(v=>
   `<div class="un"><span class="when" style="color:var(--muted)">${(v.privacy||'hidden').toUpperCase()}</span>`+
   `<span class="tt">${v.title||''}</span></div>`));
 $('upNext').innerHTML=rows.length?rows.join('')
   :'<div class="un"><span class="tt" style="opacity:.6">Nothing scheduled — the queue is empty.</span></div>';
}

// ---- compute ----
function render(){
 const igt=IG.totalViews||0,ttt=ttTotal();const allViews=D.totalViews+igt+ttt;
 // overview metric cards (aggregate across platforms)
 const allLikes=D.totalLikes+IG.media.reduce((a,m)=>a+(m.likes||0),0);
 const allCmts=D.totalComments+IG.media.reduce((a,m)=>a+(m.comments||0),0);
 const allShares=IG.media.reduce((a,m)=>a+(m.shares||0),0);
 const eng=allViews?((allLikes+allCmts+allShares)/allViews*100):0;
 $('mViews').textContent=fmt(allViews);$('mLikes').textContent=fmt(allLikes);$('mCmts').textContent=fmt(allCmts);
 $('mShares').textContent=fmt(allShares);$('mEng').textContent=eng.toFixed(2)+'%';
 renderLibrary();
 renderThumbs();drawViewsChart();
 line($('cSubs'),D.history.map(h=>({x:new Date(h.t).getTime(),y:h.subs})),'var(--amber)');
 // most-viewed across platforms
 let top=D.videos[0]?{title:D.videos[0].title,views:D.videos[0].views,url:'https://youtube.com/watch?v='+D.videos[0].videoId,platform:'YouTube'}:null;
 IG.media.forEach(m=>{if(m.views>(top?top.views:0))top={title:m.caption,views:m.views,url:m.permalink,platform:'Instagram'}});
 D.videos.forEach(v=>{const tv=+tt[v.videoId]||0;if(tv>(top?top.views:0))top={title:v.title,views:tv,url:'https://youtube.com/watch?v='+v.videoId,platform:'TikTok'}});
 $('feat').innerHTML=top?`<div class="big">${fmt(top.views)}</div><div><div><a href="${top.url}" target="_blank" style="color:var(--text);text-decoration:none">${top.title}</a></div><div class="pill">${top.platform} · top performer</div></div>`:'<div class="note">No videos yet.</div>';
 // posts/day
 const byDay={};D.posts.forEach(p=>byDay[p.date]=(byDay[p.date]||0)+1);
 bars($('cPosts'),Object.keys(byDay).sort().map(d=>({label:d,v:byDay[d]})),'var(--mint)');
 // youtube tab
 $('ytv').textContent=fmt(D.totalViews);$('ysubs').textContent=fmt(D.subs);$('ycnt').textContent=D.count;
 bars($('cPerVid'),D.videos.map(v=>({label:v.title,v:v.views})),'var(--red)');
 // YouTube list: a video can be uploaded but not visible yet, so label each
 // row LIVE or SCHEDULED rather than implying everything is published.
 $('ytList').innerHTML=D.videos.map((v,i)=>{
   const sched=!!v.publishAt||(v.privacy&&v.privacy!=='public');
   const when=v.publishAt?new Date(v.publishAt).toLocaleString([],{weekday:'short',month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}):'';
   const badge=sched?`<span class="st sched">SCHEDULED ${when}</span>`:`<span class="st live">LIVE</span>`;
   const stats=sched?'<span class="s">not published yet</span>':`${fmt(v.views)}<span class="s">${v.likes}♥ ${v.comments||0}💬</span>`;
   return `<div class="row"><span class="rank">${i+1}</span><span class="rtitle"><a href="https://youtube.com/watch?v=${v.videoId}" target="_blank">${v.title}</a> ${badge}</span><span class="rv">${stats}</span></div>`;
 }).join('');
 // instagram tab (auto)
 $('igv').textContent=fmt(igt);$('iglk').textContent=fmt(IG.media.reduce((a,m)=>a+m.likes,0));$('igcnt').textContent=IG.media.length;
 const igSorted=[...IG.media].sort((a,b)=>b.views-a.views);
 // Instagram: everything here is already published (IG has no scheduling API),
 // so label each row POSTED with its date.
 $('igList').innerHTML=igSorted.length?igSorted.map((m,i)=>{
   const d=m.timestamp?new Date(m.timestamp).toLocaleDateString([],{month:'short',day:'numeric'}):'';
   const cap=(m.caption||'').split('\n')[0];
   return `<div class="row"><span class="rank">${i+1}</span><span class="rtitle"><a href="${m.permalink}" target="_blank">${cap}</a> <span class="st live">POSTED ${d}</span>${m.type==='CAROUSEL_ALBUM'?' <span class="pill">carousel — post as Reel</span>':''}</span><span class="rv">${fmt(m.views)}<span class="s">${m.likes}♥ ${m.comments}💬 ${m.shares||0}↗</span></span></div>`;
 }).join(''):'<div class="note">No IG posts found.</div>';
 $('igNote').textContent=IG.fetchedAt?('Live from Instagram API · synced '+new Date(IG.fetchedAt).toLocaleString()):'';
 // tiktok tab
 $('ttv').textContent=fmt(ttt);$('ttcnt').textContent=Object.keys(tt).filter(k=>+tt[k]>0).length;
 // TikTok: show what has ACTUALLY been pushed to drafts (from the approval
 // queue) rather than listing every YouTube video as if it were on TikTok.
 const q=D.ttQueue||[];
 const label={posted:['IN DRAFTS','live'],skipped:['SKIPPED','skip'],
              pending:['AWAITING APPROVAL','sched'],failed:['FAILED','skip']};
 $('ttPushed').innerHTML=q.length?q.slice().reverse().map(r=>{
   const [txt,cls]=label[r.status]||[r.status.toUpperCase(),'skip'];
   const d=r.when?new Date(r.when).toLocaleDateString([],{month:'short',day:'numeric'}):'';
   return `<div class="row"><span class="rtitle">${r.title} <span class="st ${cls}">${txt}</span></span><span class="rv"><span class="s">${d}</span></span></div>`;
 }).join(''):'<div class="note">Nothing pushed to TikTok yet.</div>';
 $('ttList').innerHTML=D.videos.map(v=>`<div class="row"><span class="rtitle">${v.title}</span><input class="mv" type="number" min="0" placeholder="0" value="${tt[v.videoId]||''}" data-id="${v.videoId}"></div>`).join('');
 $('ttList').querySelectorAll('input.mv').forEach(inp=>inp.addEventListener('input',()=>{tt[inp.dataset.id]=+inp.value||0;localStorage.setItem(TTK,JSON.stringify(tt));render()}));
 // revenue tab
 const est=allViews/1000*D.rpm;$('rest').textContent=money(est);$('ract').textContent='$0.00';
 const days=Math.max(1,D.history.length>1?(new Date(D.history[D.history.length-1].t)-new Date(D.history[0].t))/86400000:1);
 $('rmo').textContent=money(est/days*30);
 $('subProg').textContent=fmt(D.subs)+' / '+fmt(D.yppSubs);$('subBar').style.width=Math.min(100,D.subs/D.yppSubs*100)+'%';
 $('viewProg').textContent=fmt(D.totalViews)+' / '+fmt(D.yppViews);$('viewBar').style.width=Math.min(100,D.totalViews/D.yppViews*100)+'%';
}
render();
// chart Delta/Cumulative toggle + time range
$('platSel').onchange=e=>{chartPlat=e.target.value;drawViewsChart()};
$('tgCumul').onclick=()=>{chartMode='cumul';$('tgCumul').classList.add('on');$('tgDelta').classList.remove('on');drawViewsChart()};
$('tgDelta').onclick=()=>{chartMode='delta';$('tgDelta').classList.add('on');$('tgCumul').classList.remove('on');drawViewsChart()};
$('rangeSel').onchange=()=>{chartRange=+$('rangeSel').value;drawViewsChart()};

// ---- assistant chat + autonomy toggle (needs control_server on :8000) ----
const chat=$('chat'),cin=$('cin'),csend=$('csend');let pend=[];
// Chat history survives page refreshes (localStorage) -- capped at 40 turns.
const HK='pf_chat_hist';let hist=[];try{hist=JSON.parse(localStorage.getItem(HK)||'[]')}catch(e){}
function saveHist(){try{localStorage.setItem(HK,JSON.stringify(hist.slice(-40)))}catch(e){}}
hist.forEach(m=>bubble(m.role==='user'?'user':'bot',typeof m.content==='string'?m.content:'(attachments)'));
// Data auto-refresh WITHOUT interrupting you: only reloads if you're not on
// the Assistant tab and not mid-typing / mid-attachment.
// Poll for FRESH data every 60s and reload only when the numbers have
// actually changed -- a blind 5-minute reload wastes work and can interrupt
// you mid-scroll for nothing. Still never reloads while you're using the
// Assistant tab or have text/attachments pending.
let lastAge=null;
setInterval(async()=>{
 const onAssist=document.querySelector('.tab[data-t=assistant]')?.classList.contains('on');
 if(onAssist||cin.value||pend.length)return;
 try{
  const r=await fetch('/api/stats-age',{cache:'no-store'});
  const j=await r.json();
  // age resets toward 0 when a refresh lands -> that's the signal to reload
  if(lastAge!==null&&j.ageMinutes<lastAge)location.reload();
  lastAge=j.ageMinutes;
  const s=$('sync');
  if(s&&j.syncing)s.textContent='refreshing…';
 }catch(e){}
},60000);
const chips=$('chips'),cfile=$('cfile');
function drawChips(){chips.innerHTML=pend.map((a,i)=>`<span class="pill" style="cursor:pointer" data-i="${i}" title="click to remove">📄 ${a.name} ✕</span>`).join('');
 chips.querySelectorAll('[data-i]').forEach(el=>el.onclick=()=>{pend.splice(+el.dataset.i,1);drawChips()})}
async function upFiles(files){for(const f of files){const fd=new FormData();fd.append('file',f);
 try{const r=await fetch('/api/upload',{method:'POST',body:fd});const j=await r.json();
  if(j.name){pend.push(j);drawChips()}}catch(e){bubble('bot','⚠️ upload failed — is the control server running?')}}}
$('cattach').onclick=()=>cfile.click();
cfile.addEventListener('change',()=>{upFiles(cfile.files);cfile.value=''});
chat.addEventListener('dragover',e=>{e.preventDefault();chat.style.outline='2px dashed var(--violet)'});
chat.addEventListener('dragleave',()=>chat.style.outline='');
chat.addEventListener('drop',e=>{e.preventDefault();chat.style.outline='';upFiles(e.dataTransfer.files)});
function bubble(role,text){const d=document.createElement('div');
 d.style.cssText='max-width:85%;padding:9px 12px;border-radius:12px;font-size:13px;white-space:pre-wrap;'+(role==='user'?'align-self:flex-end;background:var(--violet);color:#fff':'align-self:flex-start;background:var(--alt)');
 d.textContent=text;chat.appendChild(d);chat.scrollTop=chat.scrollHeight;return d}
async function send(){const m=cin.value.trim();if(!m&&!pend.length)return;cin.value='';
 const label=m+(pend.length?'  ['+pend.map(a=>a.name).join(', ')+']':'');
 bubble('user',label);hist.push({role:'user',content:m||'(sent attachments)'});saveHist();
 const atts=pend.slice();pend=[];drawChips();
 const b=bubble('bot','…');try{const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({messages:hist,attachments:atts})});
  const j=await r.json();b.textContent=j.reply;hist.push({role:'assistant',content:j.reply});saveHist()}catch(e){b.textContent='⚠️ Assistant offline — start the control server (start_control.bat) and open http://localhost:8000'}}
csend.onclick=send;cin.addEventListener('keydown',e=>{if(e.key==='Enter')send()});
const tog=$('autoTog'),slide=$('autoSlide'),knob=$('autoKnob');
function paintTog(on){slide.style.background=on?'var(--mint)':'var(--border)';knob.style.left=on?'25px':'3px';$('autoState').textContent=on?'ON — posting hourly on its own':'OFF — only posts when you tell it'}
async function loadAuto(){try{const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({messages:[{role:'user',content:'call get_autonomy and reply only ON or OFF'}]})});const j=await r.json();const on=/on/i.test(j.reply)&&!/off/i.test(j.reply);tog.checked=on;paintTog(on)}catch(e){$('autoState').textContent='(start control server to control)'}}
tog.addEventListener('change',async()=>{paintTog(tog.checked);await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({messages:[{role:'user',content:'turn autonomy '+(tog.checked?'on':'off')}]})})});
loadAuto();
</script></body></html>"""


if __name__ == "__main__":
    build()
