import streamlit as st
import scraper
import cleaner
import analyzer

# --- 页面基础配置 ---
st.set_page_config(page_title="Steam2025年度游戏热销榜舆情洞察平台", layout="wide", page_icon="🎮")

# --- 🍎 Apple 风格核心 CSS 注入 ---
st.markdown("""
    <style>
    .stApp { background-color: #F5F5F7; font-family: -apple-system, BlinkMacSystemFont, sans-serif; }
    [data-testid="stSidebar"] { background-color: #FFFFFF; border-right: 1px solid #E5E5E5; }
    
    /* 标题容器优化：强行居中对齐 */
    .header-box {
        display: flex;
        align-items: center;
        padding: 20px 0 10px 0;
    }
    .steam-logo {
        width: 50px;
        margin-right: 15px;
        filter: drop-shadow(0px 2px 4px rgba(0,0,0,0.1));
    }
    .main-title {
        font-size: 42px;
        font-weight: 700;
        color: #1D1D1F;
        margin: 0;
        letter-spacing: -0.03em;
        line-height: 1.2;
    }
    .sub-title {
        font-size: 18px;
        color: #86868B;
        margin-left: 65px; /* 对齐 Logo 后的文字起始位置 */
        margin-top: -5px;
        margin-bottom: 40px;
    }
    
    /* 其余样式保持不变 */
    .streamlit-expanderHeader { background-color: #FFFFFF; border-radius: 12px; border: 1px solid #E5E5E5; color: #1D1D1F; font-weight: 500; }
    [data-testid="stExpander"] { background-color: #FFFFFF; border-radius: 12px; border: none; box-shadow: 0 4px 12px rgba(0,0,0,0.03); margin-bottom: 15px; overflow: hidden; }
    [data-testid="stExpanderDetails"] { border-top: 1px solid #F0F0F0; }
    .stButton > button { border-radius: 999px; font-weight: 500; border: none; padding: 0.5rem 1.5rem; transition: all 0.2s ease; }
    button[kind="primary"] { background: #0071E3; color: white; box-shadow: 0 2px 5px rgba(0,113,227,0.3); }
    button[kind="primary"]:hover { background: #0077ED; transform: scale(1.02); }
    .stTextInput > div > div > input, .stSelectbox > div > div > div, .stNumberInput > div > div > input { border-radius: 10px; border: 1px solid #D2D2D7; background-color: #FFFFFF; }
    #MainMenu {visibility: hidden;} footer {visibility: hidden;}
    </style>
""", unsafe_allow_html=True)

# --- 🏆 标题区域 (修复错位问题) ---
st.markdown("""
    <div class="header-box">
        <img src="https://upload.wikimedia.org/wikipedia/commons/8/83/Steam_icon_logo.svg" class="steam-logo">
        <h1 class="main-title">Steam2025年度游戏热销榜舆情洞察平台</h1>
    </div>
    <div class="sub-title">基于海量真实玩家评论的深度语义分析系统</div>
""", unsafe_allow_html=True)

# ==========================================
# 后续逻辑 (保持不变)
# ==========================================
if 'raw_data' not in st.session_state: st.session_state.raw_data = None
if 'clean_data' not in st.session_state: st.session_state.clean_data = None

GAME_DB = {
    "1. 黑神话：悟空 (Black Myth: Wukong)": "2358720",
    "2. 艾尔登法环 (Elden Ring)": "1245620",
    "3. 幻兽帕鲁 (Palworld)": "1623730",
    "4. 博德之门 3 (Baldur's Gate 3)": "1086940",
    "5. 赛博朋克 2077 (Cyberpunk 2077)": "1091500",
    "6. 绝地潜兵 2 (Helldivers 2)": "553850",
    "7. 星空 (Starfield)": "1716740",
    "8. 只狼：影逝二度 (Sekiro)": "814380",
    "9. 荒野大镖客 2 (Red Dead Redemption 2)": "1174180",
    "10. 霍格沃茨之遗 (Hogwarts Legacy)": "990080",
    "11. 生化危机 4 重制版 (RE4 Remake)": "2050650",
    "12. 怪物猎人：荒野 (Monster Hunter Wilds)": "2246340", 
    "13. 文明 7 (Civilization VII)": "1295660", 
    "14. 空洞骑士：丝之歌 (Silksong)": "1030300", 
    "15. GTA V (Grand Theft Auto V)": "271590"
}

# 1. 采集模块
with st.container():
    with st.expander("📡 第一步：数据采集 (Extraction)", expanded=True):
        col_a, col_b = st.columns([1, 2], gap="large")
        with col_a:
            st.markdown("##### 选择目标")
            selected_game_name = st.selectbox("游戏名称", list(GAME_DB.keys()), label_visibility="collapsed")
            target_app_id = GAME_DB[selected_game_name]
        with col_b:
            st.markdown("##### 采集规模")
            c1, c2 = st.columns([3, 1])
            with c1:
                target_num = st.number_input("目标数量", 100, 5000, 1000, step=100, label_visibility="collapsed")
                st.markdown("""<div style="font-size:12px; color:#86868B; margin-top:5px;">🚀 <b>500-1000</b> (速度优先) &nbsp;|&nbsp; 🛡️ <b>2000+</b> (质量优先)</div>""", unsafe_allow_html=True)
            with c2:
                if st.button("开始采集", type="primary", use_container_width=True):
                    st.session_state.raw_data = scraper.run(app_id=target_app_id, target_count=target_num)

# 2. 清洗模块
if st.session_state.raw_data is not None:
    st.write("")
    with st.expander("🧼 第二步：数据清洗 (Cleaning)", expanded=True):
        col_c, col_d, col_btn = st.columns([2, 2, 1], gap="medium")
        with col_c:
            st.markdown("##### 好评质量阈值 (Score)")
            min_pos = st.slider("好评", 5, 100, 15, label_visibility="collapsed")
        with col_d:
            st.markdown("##### 差评质量阈值 (Score)")
            min_neg = st.slider("差评", 2, 50, 5, label_visibility="collapsed")
        with col_btn:
            st.write("")
            st.write("")
            if st.button("执行清洗", type="primary", use_container_width=True):
                st.session_state.clean_data = cleaner.process_data(st.session_state.raw_data, min_pos, min_neg, selected_game_name)
                st.session_state.review_idx = 0
        if st.session_state.clean_data is not None:
            cleaner.show_ui(st.session_state.raw_data, st.session_state.clean_data)

# 3. 分析模块
if st.session_state.clean_data is not None:
    st.markdown("---")
    analyzer.run(st.session_state.clean_data, game_name=selected_game_name)
    st.write("")
    c_dl, _ = st.columns([1, 4])
    with c_dl:
        st.download_button(f"📥 导出报告 (.csv)", data=st.session_state.clean_data.to_csv(index=False).encode('utf-8-sig'), file_name='analysis_report.csv', type="primary")