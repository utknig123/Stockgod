"""
StockGod Dashboard — high-volume scrape, deep analytics, suggestions
"""
import os
from urllib.parse import quote_plus

import httpx
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

API_URL = os.getenv("API_URL", "http://localhost:8000")
if os.path.exists("/.dockerenv"):
    API_URL = os.getenv("API_URL", "http://api:8000")

PLATFORM_LABELS = {
    "news": "News aggregators",
    "twitter": "News (legacy)",
    "reddit": "Reddit",
    "instagram": "Social (legacy)",
    "social": "StockTwits / Social",
}

ACTION_COLORS = {
    "BUY": "#1e8449",
    "HOLD_POSITIVE": "#27ae60",
    "HOLD": "#f39c12",
    "HOLD_CAUTION": "#e67e22",
    "SELL_AVOID": "#c0392b",
    "INSUFFICIENT_DATA": "#7f8c8d",
}

st.set_page_config(
    page_title="StockGod — Indian Stock Sentiment",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .main-header { font-size: 2.2rem; font-weight: 700; color: #1f4e79; margin-bottom: 0.2rem; }
    .sub-header { color: #5f6b7a; font-size: 1rem; margin-bottom: 1.2rem; }
    .suggest-box { border-radius: 12px; padding: 1.1rem 1.3rem; color: white; margin: 0.8rem 0 1.2rem 0; }
    .legend-box { background: #f0f4f8; border-radius: 8px; padding: 0.75rem; font-size: 0.85rem; line-height: 1.5; }
    .price-up { color: #1e8449; font-weight: 700; }
    .price-down { color: #c0392b; font-weight: 700; }
</style>
""", unsafe_allow_html=True)


def api_get(path: str, timeout: float = 20.0):
    try:
        r = httpx.get(f"{API_URL}{path}", timeout=timeout)
        return r.json() if r.status_code == 200 else None
    except Exception as e:
        st.error(f"API error: {e}")
        return None


def api_post(path: str, body: dict, timeout: float = 300.0):
    try:
        r = httpx.post(f"{API_URL}{path}", json=body, timeout=timeout)
        if r.status_code == 200:
            return r.json()
        st.error(f"Analyze failed ({r.status_code}): {r.text[:500]}")
        return None
    except Exception as e:
        st.error(f"Analyze request failed: {e}")
        return None


def sentiment_label(score: float) -> str:
    if score > 0.3:
        return "Bullish"
    if score > 0.1:
        return "Slightly Positive"
    if score < -0.3:
        return "Bearish"
    if score < -0.1:
        return "Slightly Negative"
    return "Neutral"


def render_suggestion(suggestion: dict):
    if not suggestion:
        return
    color = ACTION_COLORS.get(suggestion.get("action"), "#34495e")
    st.markdown(
        f"""
        <div class="suggest-box" style="background:{color}">
            <div style="font-size:1.35rem;font-weight:700">{suggestion.get('label', '')}</div>
            <div style="margin-top:0.4rem;opacity:0.95">{suggestion.get('rationale', '')}</div>
            <div style="margin-top:0.6rem;font-size:0.85rem;opacity:0.85">
                Confidence: <b>{(suggestion.get('confidence') or 'n/a').upper()}</b>
                &nbsp;·&nbsp; {suggestion.get('disclaimer', '')}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ── Sidebar ──────────────────────────────────────────────────────────
with st.sidebar:
    st.header("🎯 Analyze any stock")
    st.caption("Scrapes 100–200+ items from many Indian news/social sources")

    query = st.text_input(
        "Search",
        value=st.session_state.get("last_query", "TCS"),
        placeholder="e.g. Reliance, TCS, Swiggy, INFY",
        key="search_query",
    )

    c1, c2 = st.columns(2)
    with c1:
        do_search = st.button("🔎 Search", use_container_width=True)
    with c2:
        if st.button("🔄 Clear", use_container_width=True):
            for k in ("search_results", "analysis", "selected"):
                st.session_state.pop(k, None)
            st.rerun()

    if do_search or ("search_results" not in st.session_state and query):
        with st.spinner("Searching NSE/BSE…"):
            results = api_get(f"/api/companies/search?q={quote_plus(query)}&limit=15")
            st.session_state["search_results"] = results or []
            st.session_state["last_query"] = query

    results = st.session_state.get("search_results") or []
    selected = st.session_state.get("selected")

    if results:
        labels = {f"{r['symbol']} — {r['name']}": r for r in results}
        choice = st.selectbox("Select company", list(labels.keys()), key="company_pick")
        selected = labels[choice]
        st.session_state["selected"] = selected

    manual_symbol = st.text_input("Or enter ticker", placeholder="HDFCBANK or SWIGGY.NS")
    if manual_symbol.strip():
        sym = manual_symbol.strip().upper()
        if not sym.endswith(".NS") and not sym.endswith(".BO"):
            sym = f"{sym}.NS"
        selected = {"symbol": sym, "name": sym.split(".")[0], "keywords": []}
        st.session_state["selected"] = selected

    st.markdown("---")
    analyze_clicked = st.button(
        "⚡ Deep scrape + analytics",
        type="primary",
        use_container_width=True,
        disabled=not bool(st.session_state.get("selected")),
    )
    st.caption("Pulls ~200 posts · tries for 50 from each major source (Moneycontrol, ET, BS, Mint, Reuters…)")

    try:
        ok = httpx.get(f"{API_URL}/health", timeout=3.0).status_code == 200
        st.success("API online") if ok else st.error("API error")
    except Exception:
        st.error("API offline")


st.markdown('<p class="main-header">📈 StockGod — Indian Stock Intelligence</p>', unsafe_allow_html=True)
st.markdown(
    '<p class="sub-header">Any NSE/BSE name → multi-source scrape (100–200+ posts) → FinBERT → price + news analytics → suggestion</p>',
    unsafe_allow_html=True,
)

selected = st.session_state.get("selected")

if analyze_clicked and selected:
    with st.spinner(
        f"Deep-scraping news & social for **{selected['symbol']}** "
        "(target 100–200 posts, ~50/source where available) and scoring with FinBERT… "
        "This can take 1–3 minutes."
    ):
        analysis = api_post(
            "/api/analyze",
            {"symbol": selected["symbol"], "name": selected.get("name")},
            timeout=360.0,
        )
        if analysis:
            st.session_state["analysis"] = analysis
            st.success(
                f"Scraped & scored **{analysis.get('total_posts', 0)}** posts · "
                f"{analysis.get('source_targets', {}).get('total_sources_used', 0)} sources · "
                f"{analysis.get('source_targets', {}).get('sources_hitting_50', 0)} sources ≥ 50 items"
            )

analysis = st.session_state.get("analysis")

tab_overview, tab_sources, tab_price, tab_headlines, tab_posts, tab_market = st.tabs([
    "📊 Overview & Suggestion",
    "📡 Source Coverage",
    "💹 Price & Alignment",
    "🗞 Headlines & Themes",
    "📝 All Posts",
    "🗂 Tracked Market",
])

if not analysis:
    with tab_overview:
        st.info("👈 Search a company and click **Deep scrape + analytics**.")
        popular = api_get("/api/companies/search?q=&limit=12") or []
        if popular:
            cols = st.columns(4)
            for i, p in enumerate(popular[:12]):
                with cols[i % 4]:
                    if st.button(p["symbol"], key=f"pop_{p['symbol']}", use_container_width=True):
                        st.session_state["selected"] = p
                        st.session_state["search_results"] = [p]
                        st.rerun()
                    st.caption(p["name"][:36])
else:
    quote = analysis.get("quote") or analysis.get("analytics", {}).get("quote") or {}
    analytics = analysis.get("analytics") or {}

    # ── OVERVIEW ─────────────────────────────────────────────────────
    with tab_overview:
        st.subheader(f"{analysis['company_name']} ({analysis['company_symbol']})")
        render_suggestion(analysis.get("suggestion") or {})

        m1, m2, m3, m4, m5, m6 = st.columns(6)
        m1.metric("Posts scraped", analysis.get("total_posts", 0))
        m2.metric("Sentiment", f"{analysis.get('avg_sentiment', 0):+.2f}",
                  delta=sentiment_label(analysis.get("avg_sentiment", 0)))
        m3.metric("Positive", f"{analysis.get('positive_pct', 0):.0%}")
        m4.metric("Negative", f"{analysis.get('negative_pct', 0):.0%}")
        if quote.get("price") is not None:
            m5.metric(
                "Last price",
                f"₹{quote['price']:,.2f}",
                delta=f"{quote.get('change_pct') or 0:+.2f}%",
            )
        else:
            m5.metric("Last price", "—")
        targets = analysis.get("source_targets") or {}
        m6.metric("Sources ≥50", targets.get("sources_hitting_50", 0),
                  delta=f"{targets.get('total_sources_used', 0)} total")

        c1, c2 = st.columns(2)
        with c1:
            hist = analytics.get("sentiment_histogram") or []
            if hist:
                hdf = pd.DataFrame(hist)
                fig = px.bar(
                    hdf, x="bucket", y="count", color="bucket",
                    title="Sentiment distribution of all posts",
                    color_discrete_sequence=px.colors.diverging.RdYlGn,
                )
                fig.update_layout(height=360, template="plotly_white", showlegend=False)
                st.plotly_chart(fig, use_container_width=True)
        with c2:
            fig = go.Figure(data=[go.Pie(
                labels=["Positive", "Negative", "Neutral"],
                values=[
                    analysis.get("positive_pct", 0),
                    analysis.get("negative_pct", 0),
                    analysis.get("neutral_pct", 0),
                ],
                hole=0.45,
                marker_colors=["#2ecc71", "#e74c3c", "#95a5a6"],
            )])
            fig.update_layout(title="Average FinBERT mix", height=360, template="plotly_white")
            st.plotly_chart(fig, use_container_width=True)

        platforms = analysis.get("by_platform") or []
        if platforms:
            pdf = pd.DataFrame(platforms)
            pdf["label"] = pdf["platform"].map(lambda p: PLATFORM_LABELS.get(p, p))
            fig = px.bar(
                pdf, x="label", y="post_count", color="avg_sentiment",
                color_continuous_scale="RdYlGn", color_continuous_midpoint=0,
                text="post_count", title="Volume by channel",
            )
            fig.update_layout(height=340, template="plotly_white")
            st.plotly_chart(fig, use_container_width=True)

    # ── SOURCES ──────────────────────────────────────────────────────
    with tab_sources:
        st.subheader("Where did the data come from?")
        st.caption("Target ≈ 50 posts per source when the feed allows it; total target 100–220 unique items.")

        coverage = analytics.get("source_coverage") or []
        sources = analysis.get("by_source") or []

        if coverage:
            cdf = pd.DataFrame(coverage)
            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=cdf["source"], y=cdf["scraped"], name="Scraped",
                marker_color=["#1e8449" if h else "#3498db" for h in cdf["hit_target"]],
                text=cdf["scraped"], textposition="outside",
            ))
            fig.add_hline(y=50, line_dash="dash", line_color="#e74c3c",
                          annotation_text="Target 50")
            fig.update_layout(
                title="Posts per source (green = hit 50+ target)",
                height=420, template="plotly_white",
                xaxis_tickangle=-35,
            )
            st.plotly_chart(fig, use_container_width=True)

        src_sent = analytics.get("source_sentiment") or []
        if src_sent:
            sdf = pd.DataFrame(src_sent)
            fig = px.scatter(
                sdf, x="post_count", y="avg_sentiment", size="post_count",
                color="avg_sentiment", color_continuous_scale="RdYlGn",
                color_continuous_midpoint=0, hover_name="source",
                title="Source volume vs average sentiment",
                labels={"post_count": "Posts", "avg_sentiment": "Avg sentiment"},
            )
            fig.add_hline(y=0, line_dash="dot", line_color="gray")
            fig.update_layout(height=400, template="plotly_white")
            st.plotly_chart(fig, use_container_width=True)

            st.dataframe(
                sdf.rename(columns={
                    "source": "Source", "post_count": "Posts",
                    "avg_sentiment": "Avg Sentiment",
                    "bullish_share": "Bullish %", "bearish_share": "Bearish %",
                }),
                use_container_width=True, hide_index=True,
            )

        if sources:
            fig = px.bar(
                pd.DataFrame(sources).head(15),
                x="post_count", y="source", orientation="h",
                color="avg_sentiment", color_continuous_scale="RdYlGn",
                color_continuous_midpoint=0,
                title="Top sources by volume",
            )
            fig.update_layout(height=480, template="plotly_white", yaxis=dict(autorange="reversed"))
            st.plotly_chart(fig, use_container_width=True)

    # ── PRICE ────────────────────────────────────────────────────────
    with tab_price:
        st.subheader("Market price context (Yahoo Finance)")
        if not quote.get("price"):
            st.warning("Could not fetch live quote for this symbol.")
        else:
            a, b, c, d, e = st.columns(5)
            a.metric("Price", f"₹{quote['price']:,.2f}", delta=f"{quote.get('change_pct') or 0:+.2f}%")
            b.metric("Day high", f"₹{quote.get('day_high') or 0:,.2f}" if quote.get("day_high") else "—")
            c.metric("Day low", f"₹{quote.get('day_low') or 0:,.2f}" if quote.get("day_low") else "—")
            d.metric("52W high", f"₹{quote.get('fifty_two_week_high') or 0:,.2f}" if quote.get("fifty_two_week_high") else "—")
            e.metric("52W low", f"₹{quote.get('fifty_two_week_low') or 0:,.2f}" if quote.get("fifty_two_week_low") else "—")

            align = (analytics.get("news_vs_price") or {}).get("alignment", "unknown")
            align_msg = {
                "aligned_positive": "🟢 News sentiment and price move are both positive",
                "aligned_negative": "🔴 News sentiment and price move are both negative",
                "diverging": "🟡 News sentiment and price move diverge — dig into headlines",
                "unknown": "⚪ Not enough price context",
            }.get(align, align)
            st.info(align_msg)

            chart = quote.get("chart") or []
            if chart:
                cdf = pd.DataFrame(chart)
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=cdf["date"], y=cdf["close"], mode="lines",
                    name="Close", line=dict(width=2, color="#1f4e79"),
                    fill="tozeroy", fillcolor="rgba(31,78,121,0.08)",
                ))
                fig.update_layout(
                    title="1-month daily close",
                    height=400, template="plotly_white",
                    yaxis_title="Price (₹)",
                )
                st.plotly_chart(fig, use_container_width=True)

                if "volume" in cdf.columns:
                    fig2 = px.bar(cdf, x="date", y="volume", title="Daily volume",
                                 labels={"volume": "Volume", "date": "Date"})
                    fig2.update_layout(height=280, template="plotly_white")
                    st.plotly_chart(fig2, use_container_width=True)

            nvp = analytics.get("news_vs_price") or {}
            st.markdown(
                f"**News avg sentiment:** `{nvp.get('avg_sentiment', 0):+.2f}` · "
                f"**Day change:** `{nvp.get('price_change_pct')}%` · "
                f"**1M change:** `{nvp.get('month_change_pct')}%`"
            )

    # ── HEADLINES ────────────────────────────────────────────────────
    with tab_headlines:
        left, right = st.columns(2)
        with left:
            st.markdown("### 🟢 Most bullish headlines")
            for h in analytics.get("top_bullish") or []:
                st.markdown(f"**{h.get('score', 0):+.2f}** · `{h.get('source')}`  \n{h.get('content')}")
                if h.get("url"):
                    st.caption(h["url"])
                st.divider()
        with right:
            st.markdown("### 🔴 Most bearish headlines")
            for h in analytics.get("top_bearish") or []:
                st.markdown(f"**{h.get('score', 0):+.2f}** · `{h.get('source')}`  \n{h.get('content')}")
                if h.get("url"):
                    st.caption(h["url"])
                st.divider()

        themes = analytics.get("themes") or []
        if themes:
            tdf = pd.DataFrame(themes)
            fig = px.bar(
                tdf, x="count", y="term", orientation="h",
                title="Most mentioned themes in scraped news",
                labels={"count": "Mentions", "term": "Theme"},
            )
            fig.update_layout(height=420, template="plotly_white", yaxis=dict(autorange="reversed"))
            st.plotly_chart(fig, use_container_width=True)

    # ── POSTS ────────────────────────────────────────────────────────
    with tab_posts:
        posts = analysis.get("posts") or []
        st.subheader(f"Scored posts (showing {len(posts)} of {analysis.get('total_posts', 0)})")
        filt = st.multiselect(
            "Filter by source",
            options=sorted({p.get("source") or p.get("author") for p in posts if p.get("source") or p.get("author")}),
        )
        tone = st.selectbox("Tone filter", ["All", "Bullish (>0.15)", "Bearish (<-0.15)", "Neutral"])
        view = posts
        if filt:
            view = [p for p in view if (p.get("source") or p.get("author")) in filt]
        if tone == "Bullish (>0.15)":
            view = [p for p in view if (p.get("sentiment") or {}).get("overall", 0) > 0.15]
        elif tone == "Bearish (<-0.15)":
            view = [p for p in view if (p.get("sentiment") or {}).get("overall", 0) < -0.15]
        elif tone == "Neutral":
            view = [p for p in view if abs((p.get("sentiment") or {}).get("overall", 0)) <= 0.15]

        for post in view[:60]:
            sent = post.get("sentiment") or {}
            overall = sent.get("overall", 0)
            src = post.get("source") or post.get("author") or "?"
            with st.expander(f"{overall:+.2f} · {src} — {(post.get('content') or '')[:100]}…"):
                st.write(post.get("content", ""))
                a, b, c, d = st.columns(4)
                a.metric("Overall", f"{overall:+.2f}")
                b.metric("Pos", f"{sent.get('positive', 0):.0%}")
                c.metric("Neg", f"{sent.get('negative', 0):.0%}")
                d.metric("Neu", f"{sent.get('neutral', 0):.0%}")
                if post.get("url"):
                    st.markdown(f"[Open source]({post['url']})")

    # ── MARKET ───────────────────────────────────────────────────────
    with tab_market:
        hours = st.selectbox("Window", [6, 12, 24, 48, 72], index=2)
        overview = api_get(f"/api/sentiment/stats/overview?hours={hours}")
        if not overview or not overview.get("by_company"):
            st.info("No tracked DB data yet — run deep scrapes above.")
        else:
            cdf = pd.DataFrame(overview["by_company"])
            fig = px.bar(
                cdf, x="company_symbol", y="avg_sentiment",
                color="avg_sentiment", color_continuous_scale="RdYlGn",
                color_continuous_midpoint=0,
                text=cdf.apply(lambda r: f"{r['avg_sentiment']:+.2f} ({r['total_posts']})", axis=1),
                title="Tracked companies in DB",
            )
            fig.update_layout(height=400, template="plotly_white")
            st.plotly_chart(fig, use_container_width=True)
