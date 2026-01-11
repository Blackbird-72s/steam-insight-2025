import requests
import pandas as pd
import time
import streamlit as st

def run(app_id='2358720', target_count=2000):
    """
    执行采集任务的主函数 (V2.0: 优化网络异常提示)
    """
    st.info(f"🕷️ 爬虫启动！目标：采集 {target_count} 条有效评论...")
    
    reviews_data = []
    cursor = '*'  # Steam 翻页游标
    
    # 进度条初始化
    progress_bar = st.progress(0)
    status_text = st.empty() # 这是一个占位符，我们会不断更新它
    
    page = 0
    # 循环抓取，直到达到目标数量
    while len(reviews_data) < target_count:
        page += 1
        
        # 1. 更新 UI 状态 (正常状态)
        current_count = len(reviews_data)
        progress = min(current_count / target_count, 1.0)
        progress_bar.progress(progress)
        
        # 正常显示的文字
        status_text.markdown(f"**🔄 正在采集第 {page} 页...** (已获取: {current_count}/{target_count})")
        
        # 2. 构造 API 请求
        url = f"https://store.steampowered.com/appreviews/{app_id}?json=1"
        params = {
            'filter': 'recent',
            'language': 'schinese',
            'num_per_page': 100,
            'review_type': 'all',
            'purchase_type': 'all',
            'cursor': cursor
        }
        
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            
            # 发送请求
            response = requests.get(url, params=params, headers=headers, timeout=10)
            data = response.json()
            
            if data.get('success') == 1:
                batch_reviews = data.get('reviews', [])
                
                if not batch_reviews:
                    st.warning("⚠️ Steam 数据已全部抓取完毕，提前结束。")
                    break
                
                # 3. 提取数据
                for r in batch_reviews:
                    reviews_data.append({
                        "content": r['review'],
                        "playtime_hours": round(r['author']['playtime_forever'] / 60, 1),
                        "voted_up": r['voted_up'],
                        "votes_up": r['votes_up'],
                        "create_time": r['timestamp_created']
                    })
                
                # 4. 更新游标
                cursor = data.get('cursor', cursor)
                
                # 5. 防封禁休眠
                time.sleep(0.5)
                
            else:
                # 这种通常是 Steam 内部错误，静默重试即可
                time.sleep(1)
                continue
                
        except Exception as e:
            # ================== 修改重点在这里 ==================
            # 1. 删掉了 st.error(e) 这个大红框
            
            # 2. 在进度文字区域显示温和的橙色提示
            status_text.markdown(
                """
                <div style="color: #ff9f0a; font-weight: bold; padding: 10px; border: 1px dashed #ff9f0a; border-radius: 5px;">
                    ⚠️ 网络连接不稳定，请稍等...<br>
                    <span style="font-size:12px; font-weight:normal">若长时间没有进展请刷新网页。</span>
                </div>
                """, 
                unsafe_allow_html=True
            )
            
            # 3. 右下角弹出一个不打扰的小气泡
            st.toast('网络波动，正在自动重试...', icon='⏳')
            
            # 4. 多休息一会儿，给网络一点恢复时间
            time.sleep(3) 
            
            # 5. 继续循环，不中断程序
            continue 
            # ===================================================
            
        # 安全熔断：防止无限循环
        if page > 100:
            break

    # 采集结束
    progress_bar.progress(1.0)
    status_text.success(f"✅ 采集完成！共获取 {len(reviews_data)} 条数据")
    
    return pd.DataFrame(reviews_data)