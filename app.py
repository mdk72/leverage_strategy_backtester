import streamlit as st
import pandas as pd
from ui import tab_settings, tab_analysis, tab_lab

# Page Config
st.set_page_config(
    page_title="레버리지 적립식 투자 시뮬레이터 (Pro)",
    page_icon="📈",
    layout="wide"
)

# Sidebar
with st.sidebar:
    st.title("🚀 Navigation")
    menu = st.radio("이동", ["설정 (Settings)", "AI 상세 분석", "실험실 (Lab)", "시뮬레이션 기록 (History)"])
    
    st.info("💡 팁: 설정 탭에서 기본적인 파라미터를 먼저 지정하세요.")

# Main
if menu == "설정 (Settings)":
    tab_settings.render()
elif menu == "AI 상세 분석":
    tab_analysis.render()
elif menu == "실험실 (Lab)":
    tab_lab.render()
elif menu == "시뮬레이션 기록 (History)":
    from ui import tab_history
    tab_history.render()
