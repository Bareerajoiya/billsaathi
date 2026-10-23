"""BillSaathi - run with:  streamlit run app.py"""
import streamlit as st

import analyzer
import checks
import db

st.set_page_config(page_title="BillSaathi", page_icon="💡", layout="wide")

ICONS = {"warn": "🟠", "info": "🔵", "ok": "🟢"}
if "current_id" not in st.session_state:
    st.session_state.current_id = None


# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.header("📂 Saved bills")
    saved = db.list_analyses()
    if not saved:
        st.caption("Nothing saved yet.")
    for item in saved:
        col1, col2 = st.columns([5, 1])
        if col1.button(f"{item['title']}\n{item['created_at']}", key=f"open{item['id']}", use_container_width=True):
            st.session_state.current_id = item["id"]
            st.rerun()
        if col2.button("🗑", key=f"del{item['id']}"):
            db.delete_analysis(item["id"])
            if st.session_state.current_id == item["id"]:
                st.session_state.current_id = None
            st.rerun()
    st.divider()
    st.caption("🔒 Photo is never saved. Only numbers, checks and explanations are stored on your computer.")
    if analyzer.mock_enabled():
        st.warning("DEMO MODE (MOCK_MODEL=1): sample data, no API call.")

# --------------------------------------------------------------------- main
st.title("💡 BillSaathi")
st.write("Bijli ke bill ki photo daalein. Gemma 4 bill padhta hai, Python numbers check karta hai, "
         "aur Gemma aap ko aasaan zubaan mein samjhata hai.")

model_label = st.selectbox("Model", list(analyzer.MODELS))
model = analyzer.MODELS[model_label]

tab_upload, tab_camera = st.tabs(["📁 Upload photo", "📷 Take photo"])
with tab_upload:
    uploaded = st.file_uploader("Bill photo", type=["jpg", "jpeg", "png", "webp"])
with tab_camera:
    camera = st.camera_input("Take a photo of the bill")
photo = uploaded or camera

if st.button("🔍 Read this bill", type="primary", disabled=photo is None):
    try:
        with st.spinner("Gemma bill padh raha hai..."):
            raw = analyzer.extract_bill(model, photo.getvalue())
        data = checks.normalize_extraction(raw)
        if not data["is_electricity_bill"]:
            st.error("Ye bijli ka bill nahi lagta. Kuch save nahi kiya gaya.")
        else:
            flags = checks.run_checks(data)
            title = f"{data['company'] or 'Bill'} {data['billing_month'] or ''}".strip()
            st.session_state.current_id = db.save_analysis(title, model, data, flags)
            st.rerun()
    except analyzer.BillSaathiError as exc:
        st.error(str(exc))

# ------------------------------------------------------------------- result
record = db.get_analysis(st.session_state.current_id) if st.session_state.current_id else None
if record:
    data, flags = record["extracted"], record["checks"]
    st.divider()
    st.subheader(f"{record['title']}  ·  Rs {data.get('total_payable') or '?'}")

    st.markdown("### ✅ Checks (done by code, not by AI)")
    for f in flags:
        st.markdown(f"{ICONS[f['severity']]} **{f['title']}** — {f['detail']}")
    if not flags:
        st.caption("Not enough data for any check.")
    st.caption("BillSaathi kabhi nahi kehta ke bill ghalat hai. Ye sirf bata'ta hai ke kya check karna chahiye. "
               "Numbers ko kagaz wale bill se zaroor milayein.")

    history = [{"month": r["month"], "units": r["units"]} for r in reversed(data.get("unit_history", []))]
    if data.get("units_consumed") is not None:
        history.append({"month": f"{data.get('billing_month') or 'This bill'}", "units": data["units_consumed"]})
    if history:
        st.markdown("### 📊 Units by month")
        st.bar_chart(history, x="month", y="units", sort=False)
        st.caption(f"Reference: protected-consumer limit used here = {checks.PROTECTED_UNITS_LIMIT} units (confirm with your company).")

    with st.expander("📄 Bill details (compare with your paper bill)"):
        st.json({k: v for k, v in data.items() if v not in (None, [], "")})

    st.markdown("### 💬 Explanation")
    language = st.radio("Language", list(analyzer.LANGUAGES), horizontal=True)
    cached = record["explanations"].get(language)
    if cached is None and st.button(f"Explain in {language}"):
        try:
            with st.spinner("Gemma samjha raha hai..."):
                cached = analyzer.explain_bill(record["model"], data, flags, language)
            db.save_explanation(record["id"], language, cached)
        except analyzer.BillSaathiError as exc:
            st.error(str(exc))
    if cached:
        rtl = language == "اردو"
        style = "direction:rtl;text-align:right;font-size:1.1rem;" if rtl else ""
        st.markdown(f"<div style='{style}'>{cached['summary']}</div>", unsafe_allow_html=True)
        for title, key in (("Worth checking", "what_to_check"), ("Next steps", "next_steps")):
            if cached.get(key):
                st.markdown(f"**{title}**")
                items = "".join(f"<li>{x}</li>" for x in cached[key])
                st.markdown(f"<div style='{style}'><ul>{items}</ul></div>", unsafe_allow_html=True)
        if cached.get("draft_request"):
            st.markdown("**✉️ Draft request to the sub-division office** (use the copy icon on the box)")
            st.code(cached["draft_request"], language=None)