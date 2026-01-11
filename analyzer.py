import altair as alt
import streamlit as st
import pandas as pd
import re
import json
import concurrent.futures
import time
from openai import OpenAI

# =======================================================
# 🔧 配置区域
# =======================================================
DEEPSEEK_API_KEY = st.secrets.get("DEEPSEEK_API_KEY", "")
BASE_URL = "https://api.deepseek.com"

# =======================================================
# 1. 本地规则引擎 (Fallback)
# =======================================================
LOCAL_FALLBACK_DB = {
    "通用": {
        "positive": {
            "画面表现": {"kws": ["画面", "画质", "风景", "光影", "美术"], "desc": "视觉效果出色，美术风格符合大众审美。"},
            "游戏性": {"kws": ["好玩", "上头", "有趣", "机制", "玩法"], "desc": "核心玩法设计有趣，具有较高的可玩性。"},
            "剧情叙事": {"kws": ["剧情", "故事", "结局", "人设", "角色"], "desc": "叙事完整，角色塑造较为成功。"}
        },
        "negative": {
            "优化问题": {"kws": ["掉帧", "卡顿", "闪退", "优化"], "desc": "存在明显的性能问题，影响流畅度。"},
            "Bug故障": {"kws": ["bug", "BUG", "报错", "坏档"], "desc": "技术故障较多，急需修复。"},
            "网络联机": {"kws": ["掉线", "连不上", "服务器", "延迟"], "desc": "网络体验不佳，联机稳定性差。"}
        }
    }
}

# =======================================================
# 2. LLM 核心逻辑 (细粒度并发 Map-Reduce)
# =======================================================

def get_llm_client():
    return OpenAI(api_key=DEEPSEEK_API_KEY, base_url=BASE_URL)

def map_phase_worker(args):
    """ 
    Map 阶段 Worker：只负责分析一个小切片 
    返回: (sentiment_type, summary_text)
    """
    text_chunk, game_name, sentiment_type = args
    client = get_llm_client()
    target_type = "优点/爽点" if sentiment_type == "positive" else "缺点/槽点"
    
    prompt = f"""
    分析对象：游戏《{game_name}》的玩家评论片段。
    任务：请快速阅读以下评论，简要列出其中提到的最核心的 3-5 个【{target_type}】。
    要求：如果有玩家具体提到了某个关卡、BOSS或地图的名字，请务必在摘要中保留。
    评论片段：
    {text_chunk}
    """
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3
        )
        return (sentiment_type, response.choices[0].message.content)
    except Exception:
        return (sentiment_type, "")

def reduce_phase_worker(combined_summaries, game_name, sentiment_type):
    """ Reduce 阶段 Worker：负责汇总 """
    client = get_llm_client()
    target_type = "优点/爽点" if sentiment_type == "positive" else "缺点/槽点"
    is_negative = "缺点" in target_type or "槽点" in target_type
    
    entity_instruction = "4. 【实体提取（NER）】：识别被频繁吐槽的具体关卡、BOSS或地图名（如‘妙音’），列入 entities 字段。" if is_negative else "4. 【实体提取（NER）】：识别高光时刻的具体关卡或BOSS名，列入 entities 字段。"
    
    system_prompt = f"""
    你是一位资深游戏主编。任务是分析《{game_name}》的【{target_type}】报告。
    请遵循：1.去重聚合 2.思维链推理 3.格式化输出
    {entity_instruction}
    
    【重要】必须严格输出为以下 JSON 格式对象：
    {{
        "insights": [
            {{"category": "核心词", "desc": "专业评价...", "score": 95}},
            {{"category": "核心词", "desc": "专业评价...", "score": 80}}
        ],
        "entities": ["名称1", "名称2"] 
    }}
    """
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"汇总摘要：\n{combined_summaries}"}
            ],
            temperature=0.3,
            stream=False
        )
        content = response.choices[0].message.content
        if "```" in content: content = content.replace("```json", "").replace("```", "")
        return json.loads(content)
    except Exception as e:
        print(f"Reduce Error: {e}")
        return None

def execute_granular_analysis(pos_text_series, neg_text_series, game_name):
    """
    细粒度并发调度器
    """
    CHUNK_SIZE = 3000
    MAX_CHUNKS_PER_TYPE = 4
    
    # 1. 准备数据切片
    full_pos = " ".join(pos_text_series.astype(str).tolist())
    full_neg = " ".join(neg_text_series.astype(str).tolist())
    
    pos_chunks = [full_pos[i:i+CHUNK_SIZE] for i in range(0, len(full_pos), CHUNK_SIZE)][:MAX_CHUNKS_PER_TYPE]
    neg_chunks = [full_neg[i:i+CHUNK_SIZE] for i in range(0, len(full_neg), CHUNK_SIZE)][:MAX_CHUNKS_PER_TYPE]
    
    total_map_tasks = len(pos_chunks) + len(neg_chunks)
    if total_map_tasks == 0: return None
    
    map_results = {"positive": [], "negative": []}
    
    # 2. Map 阶段并发执行
    # 修改点：初始提示文案
    progress_bar = st.progress(0, text="正在初始化并发分析任务，请稍后：）...")
    completed_tasks = 0
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        futures = []
        
        # 提交好评任务
        for i, chunk in enumerate(pos_chunks):
            f = executor.submit(map_phase_worker, (chunk, game_name, "positive"))
            f.meta_info = f"好评切片 {i+1}/{len(pos_chunks)}"
            futures.append(f)
            
        # 提交差评任务
        for i, chunk in enumerate(neg_chunks):
            f = executor.submit(map_phase_worker, (chunk, game_name, "negative"))
            f.meta_info = f"差评切片 {i+1}/{len(neg_chunks)}"
            futures.append(f)
            
        # 监听进度
        for future in concurrent.futures.as_completed(futures):
            completed_tasks += 1
            st_type, summary = future.result()
            if summary:
                map_results[st_type].append(summary)
            
            # 计算进度
            map_progress = (completed_tasks / total_map_tasks) * 0.9
            
            # === 修改点：这里的文案改成了你要求的 ===
            progress_bar.progress(map_progress, text=f"正在以并发结构分析评论，请稍后：） (当前处理: {future.meta_info})")
            
    # 3. Reduce 阶段
    progress_bar.progress(0.92, text="⚡ 正在聚合语义并提取实体 (Reduce Phase)...")
    
    final_res = {}
    
    # Reduce Positive
    if map_results["positive"]:
        pos_out = reduce_phase_worker("\n---\n".join(map_results["positive"]), game_name, "positive")
        final_res["positive"] = pos_out
    
    # Reduce Negative
    if map_results["negative"]:
        neg_out = reduce_phase_worker("\n---\n".join(map_results["negative"]), game_name, "negative")
        final_res["negative"] = neg_out
        
    progress_bar.progress(1.0, text="✅ 分析完成")
    time.sleep(0.5) 
    progress_bar.empty()
    
    return final_res

# =======================================================
# 3. RAG 核心逻辑
# =======================================================
def call_deepseek_rag(df, query, game_name):
    client = get_llm_client()
    relevant_reviews = df[df['clean_content'].str.contains(query, case=False, na=False)]
    
    if relevant_reviews.empty:
        return f"🤔 在当前的评论样本中，未找到关于“{query}”的直接讨论。请尝试更换关键词。"
    
    context_reviews = relevant_reviews['clean_content'].head(40).tolist()
    context_text = "\n".join(context_reviews)
    review_count = len(relevant_reviews)
    
    system_prompt = f"""
    你是一位《{game_name}》的游戏改进顾问。用户正在查询关于【{query}】的反馈。
    系统已检索到 {review_count} 条相关评论，请基于上下文回答。
    请包含：1.现状总结 2.具体细节 3.改进建议。
    语气：客观、专业。
    """
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"上下文数据：\n{context_text}"}
            ],
            temperature=0.4
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"⚠️ RAG 生成失败: {e}"

# =======================================================
# 4. 退款原因分析包装
# =======================================================
def analyze_refund_reasons(text_series, game_name):
    if text_series.empty: return []
    client = get_llm_client()
    full_text = " ".join(text_series.astype(str).tolist())[:4000]
    
    with st.status("AI 正在侦测退款诱因...", expanded=True) as status:
        p_bar = st.progress(0, text="正在聚合退款评论上下文...")
        time.sleep(0.3) 
        
        system_prompt = f"""
        分析《{game_name}》的2小时内退款评论。找出 Top 5 劝退原因。
        严格输出 JSON: [ {{"category": "原因", "desc": "简述", "score": 90}} ]
        """
        
        p_bar.progress(40, text="DeepSeek 正在分析核心痛点...")
        
        try:
            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": full_text}
                ],
                temperature=0.3
            )
            content = response.choices[0].message.content
            if "```" in content: content = content.replace("```json", "").replace("```", "")
            
            p_bar.progress(100, text="分析完成")
            status.update(label="✅ 退款原因诊断完成", state="complete", expanded=False)
            return json.loads(content)
        except:
            status.update(label="⚠️ 分析失败", state="error", expanded=False)
            return []

# =======================================================
# 5. 辅助函数
# =======================================================
def process_llm_result(llm_json_result):
    if not llm_json_result: return [], []
    insights = llm_json_result.get("insights", [])
    entities = llm_json_result.get("entities", [])
    
    if len(insights) >= 2:
        if insights[0]['score'] > (insights[1]['score'] * 1.2): insights[0]['is_dominant'] = True
        else: insights[0]['is_dominant'] = False
        for i in range(1, len(insights)): insights[i]['is_dominant'] = False
    elif len(insights) == 1: insights[0]['is_dominant'] = True
    
    return insights, entities

def get_fallback_result(text_series, sentiment_type):
    category_scores = []
    db_key = "通用" 
    current_db = LOCAL_FALLBACK_DB.get(db_key).get(sentiment_type, {})
    full_text = " ".join(text_series.astype(str).tolist())
    for category, info in current_db.items():
        score = 0
        for kw in info['kws']: score += len(re.findall(kw, full_text, re.IGNORECASE))
        if score > 0: category_scores.append({"category": category, "score": score, "desc": info['desc']})
    sorted_cats = sorted(category_scores, key=lambda x: x['score'], reverse=True)
    top_3 = sorted_cats[:3]
    if len(top_3) >= 1: top_3[0]['is_dominant'] = True
    return top_3, []

# =======================================================
# 6. 主函数
# =======================================================
def run(df, game_name="通用游戏"):
    if df.empty:
        st.warning("⚠️ 数据为空")
        return

    st.markdown("### 📊 舆情驾驶舱")
    
    # --- Part 1: 指标 ---
    with st.container():
        col1, col2 = st.columns([2, 1], gap="large")
        with col1:
            st.markdown("**游玩时长分布**")
            chart = alt.Chart(df).mark_circle(size=80, opacity=0.6).encode(
                x=alt.X('playtime_hours', title='Hours Played'),
                y=alt.Y('votes_up', title='Helpful Votes'),
                color=alt.Color('voted_up', scale=alt.Scale(range=['#FF3B30', '#34C759']), legend=None),
                tooltip=['clean_content']
            ).interactive().properties(height=320)
            st.altair_chart(chart, use_container_width=True)
        with col2:
            st.markdown("**核心指标**")
            pos_rate = df['voted_up'].mean() * 100
            churn_rate = len(df[(df['playtime_hours']<=2) & (df['voted_up']==False)]) / len(df) * 100
            st.markdown(f"""
            <div style="background:white; padding:20px; border-radius:16px; margin-bottom:15px; box-shadow:0 4px 10px rgba(0,0,0,0.03);">
                <div style="color:#86868B; font-size:13px; font-weight:500;">总体好评率</div>
                <div style="color:#1D1D1F; font-size:32px; font-weight:700;">{pos_rate:.1f}%</div>
            </div>
            <div style="background:white; padding:20px; border-radius:16px; box-shadow:0 4px 10px rgba(0,0,0,0.03);">
                <div style="color:#86868B; font-size:13px; font-weight:500;">2小时劝退率</div>
                <div style="color:{'#34C759' if churn_rate < 1 else '#FF3B30'}; font-size:32px; font-weight:700;">{churn_rate:.1f}%</div>
            </div>
            """, unsafe_allow_html=True)

    # --- Part 2: 退款诊断 ---
    st.write("")
    st.markdown("### ⏱️ 退款健康度诊断")
    refund_neg_df = df[(df['playtime_hours'] <= 2.0) & (df['voted_up'] == False)]
    total_reviews = len(df)
    churn_rate = (len(refund_neg_df) / total_reviews) * 100 if total_reviews > 0 else 0
    if churn_rate < 1.0: status, color = "健康 Excellent", "#34C759"
    elif churn_rate < 2.5: status, color = "亚健康 Warning", "#FF9F0A"
    else: status, color = "高危 Critical", "#FF3B30"

    col_d1, col_d2 = st.columns([1, 2], gap="large")
    with col_d1:
        st.markdown(f"""
        <div style="background:white; padding:24px; border-radius:18px; box-shadow:0 4px 20px rgba(0,0,0,0.04); height:100%">
            <div style="font-size:14px; color:#86868B; margin-bottom:10px;">2小时流失风险</div>
            <div style="font-size:32px; font-weight:600; color:{color}; margin-bottom:10px">{status}</div>
            <div style="font-size:48px; font-weight:700; color:#1D1D1F; margin-bottom:20px">{churn_rate:.1f}%</div>
            <div style="height:8px; width:100%; background:#F5F5F7; border-radius:4px; overflow:hidden;">
                <div style="height:100%; width:{min(churn_rate*10, 100)}%; background:{color};"></div>
            </div>
        </div>
        """, unsafe_allow_html=True)
    with col_d2:
        if not refund_neg_df.empty:
            if "sk-" in DEEPSEEK_API_KEY:
                churn_reasons = analyze_refund_reasons(refund_neg_df['clean_content'], game_name)
            else:
                churn_reasons, _ = get_fallback_result(refund_neg_df['clean_content'], "negative")
            
            if churn_reasons:
                st.markdown(f"**🚨 核心劝退原因 (Top {len(churn_reasons)})**")
                for item in churn_reasons:
                    st.markdown(f"""
                    <div style="background:white; padding:16px; border-radius:12px; margin-bottom:10px; border-left:4px solid #FF3B30; box-shadow:0 2px 8px rgba(0,0,0,0.02);">
                        <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
                            <span style="font-weight:600; color:#1D1D1F;">{item['category']}</span>
                            <span style="font-size:12px; color:#FF3B30; font-weight:bold;">{item['score']} 热度</span>
                        </div>
                        <div style="font-size:13px; color:#6E6E73;">{item['desc']}</div>
                    </div>""", unsafe_allow_html=True)
            else: st.info("样本不足，无法提取原因")
        else: st.markdown(f"""<div style="background:white; padding:24px; border-radius:18px; height:100%; display:flex; align-items:center; justify-content:center; color:#34C759; font-weight:500;">🎉 完美开局！</div>""", unsafe_allow_html=True)

    # --- Part 3: DeepSeek 深度洞察 ---
    st.write("")
    st.markdown("### 🧠 DeepSeek 深度语义洞察")
    
    if 'analysis_cache' not in st.session_state: st.session_state.analysis_cache = {}
    if 'last_game_analyzed' not in st.session_state: st.session_state.last_game_analyzed = ""
    cache_key = game_name
    need_analysis = (cache_key != st.session_state.last_game_analyzed) or (cache_key not in st.session_state.analysis_cache)

    pos_insights, pos_entities, neg_insights, neg_entities = [], [], [], []
    model_used = "本地规则引擎 (Rule-Based)"

    if need_analysis:
        pos_texts = df[df['voted_up'] == True]['clean_content']
        neg_texts = df[df['voted_up'] == False]['clean_content']
        
        if "sk-" in DEEPSEEK_API_KEY:
            llm_results = execute_granular_analysis(pos_texts, neg_texts, game_name)
            if llm_results:
                st.session_state.analysis_cache[cache_key] = llm_results
                st.session_state.last_game_analyzed = cache_key
                model_used = "DeepSeek (Granular Map-Reduce)"
        else:
            p_in, _ = get_fallback_result(pos_texts, "positive")
            n_in, _ = get_fallback_result(neg_texts, "negative")
            st.session_state.analysis_cache[cache_key] = {
                "positive": {"insights": p_in, "entities": []},
                "negative": {"insights": n_in, "entities": []}
            }
            st.session_state.last_game_analyzed = cache_key

    if cache_key in st.session_state.analysis_cache:
        cached = st.session_state.analysis_cache[cache_key]
        if "positive" in cached: pos_insights, pos_entities = process_llm_result(cached["positive"])
        if "negative" in cached: neg_insights, neg_entities = process_llm_result(cached["negative"])
        if "sk-" in DEEPSEEK_API_KEY: model_used = "DeepSeek (Granular Map-Reduce)"

    st.caption(f"🚀 分析引擎状态: **{model_used}**")
    
    c_insight1, c_insight2 = st.columns(2, gap="large")
    def render_insight_card(title, insights, entities, color, entity_title):
        st.markdown(f"**{title}**")
        if not insights:
            st.info("数据不足")
            return
        for item in insights:
            is_dom = item.get('is_dominant')
            border_left = f"4px solid {color}" if is_dom else "1px solid #E5E5E5"
            badge = f"<span style='background:{color}; color:white; padding:3px 8px; border-radius:6px; font-size:11px; font-weight:600; margin-left:8px; vertical-align:middle'>TOP FOCUS</span>" if is_dom else ""
            st.markdown(f"""
            <div style="background:white; border-radius:14px; padding:20px; margin-bottom:12px; border: 1px solid rgba(0,0,0,0.03); border-left:{border_left}; box-shadow: 0 4px 12px rgba(0,0,0,0.03);">
                <div style="font-size:16px; font-weight:600; color:#1D1D1F; margin-bottom:8px; display:flex; align-items:center;">{item['category']} {badge}</div>
                <div style="font-size:13px; color:#6E6E73; line-height:1.5; margin-bottom:12px;">{item['desc']}</div>
                <div style="height:6px; width:100%; background:#F5F5F7; border-radius:3px; overflow:hidden;">
                    <div style="height:100%; width:{min(item['score'], 100)}%; background:{color};"></div>
                </div>
            </div>""", unsafe_allow_html=True)
        if entities:
            tags_html = "".join([f"<span style='background:{color}15; color:{color}; padding:4px 10px; border-radius:8px; font-size:12px; font-weight:600; margin-right:8px; margin-bottom:8px; display:inline-block; border:1px solid {color}30'>{e}</span>" for e in entities[:6]])
            st.markdown(f"""
            <div style="margin-top:20px; padding:15px; border-radius:12px; border:1px dashed {color}60; background:{color}05">
                <div style="font-size:12px; font-weight:700; color:{color}; margin-bottom:8px; text-transform:uppercase; letter-spacing:0.5px;">{entity_title} (AI 实体识别)</div>
                <div>{tags_html}</div>
            </div>""", unsafe_allow_html=True)

    with c_insight1: render_insight_card("✅ 核心优势", pos_insights, pos_entities, "#34C759", "✨ 高光时刻 / 明星关卡")
    with c_insight2: render_insight_card("❌ 核心痛点", neg_insights, neg_entities, "#FF3B30", "💀 重点改进元素 / 问题关卡")

    # --- Part 4: RAG ---
    st.write("")
    st.markdown("---")
    st.markdown("### 🤖 RAG 专项分析 (基于检索增强生成)")
    st.caption("输入你想了解的维度，AI 将自动检索相关评论并给出改进方案。")

    with st.container():
        c_q1, c_q2 = st.columns([4, 1], gap="medium")
        with c_q1:
            user_query = st.text_input("请输入查询维度", placeholder="例如：空气墙、优化、BGM...", label_visibility="collapsed", key="rag_query_input")
        with c_q2:
            ask_btn = st.button("开始分析 ➔", type="primary", use_container_width=True)

        if ask_btn and user_query:
            if "sk-" not in DEEPSEEK_API_KEY:
                st.error("⚠️ 请先配置 DeepSeek API Key 才能使用 RAG 功能。")
            else:
                with st.spinner(f"正在检索关于“{user_query}”的评论并生成方案..."):
                    rag_response = call_deepseek_rag(df, user_query, game_name)
                
                st.markdown(f"""
                <div style="background:#F5F5F7; border-radius:16px; padding:24px; border:1px solid #E5E5E5; margin-top:20px;">
                    <div style="font-size:14px; color:#86868B; margin-bottom:10px; font-weight:600;">🤖 AI 咨询报告：{user_query}</div>
                    <div style="font-size:16px; color:#1D1D1F; line-height:1.8; white-space: pre-wrap;">{rag_response}</div>
                </div>

                """, unsafe_allow_html=True)
