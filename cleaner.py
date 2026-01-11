import pandas as pd
import re
import streamlit as st

# --- 简易关键词库 (用于计算相关度权重) ---
# 只要命中这些词，说明评论内容与游戏核心体验高度相关
RELEVANCE_KEYWORDS = {
    "通用": ["画面", "画质", "优化", "掉帧", "卡顿", "剧情", "故事", "手感", "打击感", "BGM", "音乐", "配音", "BUG", "闪退", "服务器", "联机", "好玩", "无聊"],
    "黑神话": ["空气墙", "定身", "大头", "虎先锋", "西游", "神话", "美术", "古建", "动作", "棍法", "劈棍", "戳棍", "立棍", "变身", "葫芦", "妖怪", "天命人"],
    "星空": ["飞船", "造船", "加载", "黑屏", "读条", "星球", "空旷", "探索", "NASA", "贝塞斯达", "陶德", "任务", "阵营", "哨站", "改装"],
    "艾尔登": ["开放世界", "女武神", "碎星", "老婆", "菈妮", "梅琳娜", "受苦", "骨灰", "战技", "法环", "宫崎英高", "指头", "黄金树"],
    "幻兽": ["帕鲁", "宝可梦", "缝合", "打工", "流水线", "资本", "压榨", "配种", "词条", "联机", "服务器", "球"],
    "赛博朋克": ["夜之城", "强尼", "银手", "义体", "黑客", "大厦", "荒坂", "浮空车", "光追", "甚至", "动画", "边缘行者"]
}

def process_data(df, min_pos_score=10, min_neg_score=5, game_name="通用"):
    """
    逻辑层：基于【字数 + 相关度】的加权筛选
    min_pos_score: 好评的最低质量分
    min_neg_score: 差评的最低质量分
    """
    if df.empty: return df
    
    # 1. 确定当前游戏的关键词列表
    # 简单的模糊匹配逻辑
    db_key = "通用"
    for key in RELEVANCE_KEYWORDS.keys():
        if key in game_name:
            db_key = key
            break
    keywords = RELEVANCE_KEYWORDS[db_key] + RELEVANCE_KEYWORDS["通用"]
    
    # 2. 定义清洗与打分函数
    def _clean_text(text):
        if not isinstance(text, str): return ""
        text = re.sub(r'展开\d+条.*', '', text)
        text = re.sub(r'查看更多.*', '', text)
        text = re.sub(r'IP属地.*', '', text)
        text = re.sub(r'\d{4}-\d{1,2}-\d{1,2}', '', text)
        text = re.sub(r'\n+', ' ', text)
        return text.strip()

    def _calculate_score(text):
        if not isinstance(text, str): return 0
        
        # A. 基础分：汉字数量
        chinese_count = len(re.findall(r'[\u4e00-\u9fa5]', text))
        
        # B. 加权分：关键词命中数 (每个关键词 = 5 分权重)
        # 这意味着：如果你提到了 1 个核心词（如“空气墙”），相当于你多写了 5 个字
        keyword_hits = 0
        for kw in keywords:
            if kw in text:
                keyword_hits += 1
        
        # 总分 = 字数 + (关键词数 * 5)
        total_score = chinese_count + (keyword_hits * 5)
        return total_score

    # 3. 执行处理
    df_clean = df.copy()
    df_clean['clean_content'] = df_clean['content'].apply(_clean_text)
    
    # 计算质量分
    df_clean['quality_score'] = df_clean['clean_content'].apply(_calculate_score)
    # 计算纯字数 (为了后续展示用)
    df_clean['chinese_len'] = df_clean['clean_content'].apply(lambda x: len(re.findall(r'[\u4e00-\u9fa5]', x)))
    
    # 4. 双轨过滤 (基于 Quality Score 而不是纯字数)
    mask_pos = (df_clean['voted_up'] == True) & (df_clean['quality_score'] >= min_pos_score)
    mask_neg = (df_clean['voted_up'] == False) & (df_clean['quality_score'] >= min_neg_score)
    
    df_final = df_clean[mask_pos | mask_neg].reset_index(drop=True)
    
    # 排序权重 (依然保留点赞权重)
    df_final['rank_score'] = df_final['votes_up'] + (df_final['quality_score'] * 0.2)
    
    return df_final

def show_ui(df_raw, df_final):
    """
    展示层 (Apple Style White Cards - UI 保持不变)
    """
    if df_final is None or df_final.empty:
        st.warning("⚠️ 数据为空")
        return

    # 1. 顶部指标
    removed_rate = ((len(df_raw) - len(df_final)) / len(df_raw)) * 100
    c1, c2, c3 = st.columns(3)
    c1.metric("原始数据", f"{len(df_raw)}")
    c2.metric("精选评论", f"{len(df_final)}")
    c3.metric("过滤率", f"{removed_rate:.1f}%")

    st.write("")
    st.markdown("#### 🌟 舆情双雄榜")
    st.caption("基于【内容深度 + 游戏相关度 + 获赞数】综合排序")

    # 2. 数据准备
    df_pos_top = df_final[df_final['voted_up'] == True].sort_values('rank_score', ascending=False).head(10).reset_index(drop=True)
    df_neg_top = df_final[df_final['voted_up'] == False].sort_values('rank_score', ascending=False).head(5).reset_index(drop=True)

    # 3. 状态管理
    if 'idx_pos' not in st.session_state: st.session_state.idx_pos = 0
    if 'exp_pos' not in st.session_state: st.session_state.exp_pos = False
    if 'idx_neg' not in st.session_state: st.session_state.idx_neg = 0
    if 'exp_neg' not in st.session_state: st.session_state.exp_neg = False
    
    if st.session_state.idx_pos >= len(df_pos_top): st.session_state.idx_pos = 0
    if st.session_state.idx_neg >= len(df_neg_top): st.session_state.idx_neg = 0

    # 4. 左右布局
    col_left, col_right = st.columns(2, gap="large")

    # === 左侧好评 ===
    with col_left:
        c_nav1, c_nav2 = st.columns([3, 1])
        with c_nav1: st.markdown(f"**👍 核心好评** <span style='color:#86868B; font-size:14px'>(No.{st.session_state.idx_pos + 1}/10)</span>", unsafe_allow_html=True)
        with c_nav2: 
            if st.button("Next ➔", key="btn_next_pos"):
                st.session_state.idx_pos = (st.session_state.idx_pos + 1) % len(df_pos_top)
                st.session_state.exp_pos = False
                st.rerun()
        
        if not df_pos_top.empty:
            _render_apple_card(df_pos_top.iloc[st.session_state.idx_pos], "pos")

    # === 右侧差评 ===
    with col_right:
        c_nav3, c_nav4 = st.columns([3, 1])
        with c_nav3: st.markdown(f"**👎 核心差评** <span style='color:#86868B; font-size:14px'>(No.{st.session_state.idx_neg + 1}/5)</span>", unsafe_allow_html=True)
        with c_nav4:
            if st.button("Next ➔", key="btn_next_neg"):
                st.session_state.idx_neg = (st.session_state.idx_neg + 1) % len(df_neg_top)
                st.session_state.exp_neg = False
                st.rerun()
        
        if not df_neg_top.empty:
            _render_apple_card(df_neg_top.iloc[st.session_state.idx_neg], "neg")

def _render_apple_card(row, type_key):
    """
    渲染 Apple 风格的卡片
    """
    expanded_key = f"exp_{type_key}"
    is_pos = (type_key == "pos")
    
    # 颜色变量
    accent_color = "#34C759" if is_pos else "#FF3B30"
    icon = "Recommend" if is_pos else "Not Recommended"
    
    content = row['clean_content']
    is_long = len(content) > 100
    is_expanded = st.session_state[expanded_key]
    display_content = content[:100] + "..." if (is_long and not is_expanded) else content
    
    # 质量分显示 (Score)
    quality_score = int(row.get('quality_score', 0))
    
    # 卡片 HTML
    st.markdown(f"""
    <div style="
        background-color: #FFFFFF;
        border-radius: 18px;
        padding: 24px;
        box-shadow: 0 4px 20px rgba(0,0,0,0.05);
        border: 1px solid rgba(0,0,0,0.02);
        margin-bottom: 15px;
        transition: transform 0.2s;
    ">
        <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:16px;">
            <div style="display:flex; align-items:center;">
                <div style="
                    background-color: {accent_color}; 
                    color: white; 
                    padding: 4px 12px; 
                    border-radius: 99px; 
                    font-size: 12px; 
                    font-weight: 600;
                    margin-right: 10px;">
                    {icon}
                </div>
                <div style="color: #86868B; font-size: 13px; font-weight:500;">
                    {row['playtime_hours']}h Playtime
                </div>
            </div>
            <div style="font-size:12px; font-weight:700; color:#1D1D1F; background:#F5F5F7; padding:4px 8px; border-radius:6px;">
                💎 质量分: {quality_score}
            </div>
        </div>
        <div style="
            color: #1D1D1F; 
            font-size: 15px; 
            line-height: 1.6; 
            font-family: -apple-system, sans-serif;
            font-weight: 400;">
            {display_content}
        </div>
        <div style="margin-top:10px; font-size:12px; color:#86868B;">
            ❤️ {row['votes_up']} 人觉得有用
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    if is_long:
        btn_txt = "收起" if is_expanded else "展开更多"
        if st.button(btn_txt, key=f"btn_exp_{type_key}_{row.name}"):
            st.session_state[expanded_key] = not st.session_state[expanded_key]
            st.rerun()