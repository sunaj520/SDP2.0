from taipy import Gui
from taipy.gui import State
import pandas as pd
import matplotlib.pyplot as plt
import warnings
from datetime import datetime, timedelta
import threading
import time

warnings.filterwarnings('ignore')

# 基础配置（已修复字体）
plt.switch_backend('Agg')
plt.rcParams['font.sans-serif'] = ['SimHei', 'Deja Vu Sans']
plt.rcParams['axes.unicode_minus'] = False

# CSV路径
CSV_PATH = r'\\retcn484-nt0001\Common\IT\report\report.csv'

# ======================
# 全局变量【完全原样】
# ======================
sel_store = "请选择"
sel_store_b = "请选择"
sel_date = None
sel_channel = "全部渠道"

total_sales = 0
sales_target = 0
completion_rate = "0.%"
total_visitors = 0

sales_dual_data = pd.DataFrame({
    'hour': list(range(9, 24)),
    '门店销售': [0.0] * 15,
    '对比门店销售': [0.0] * 15,
    '门店销售_text': [''] * 15,
    '对比门店销售_text': [''] * 15
})

forecast_two_color = pd.DataFrame({
    'hour': list(range(9, 24)),
    '真实销售': [None] * 15,
    '预测销售': [None] * 15,
    'label': [''] * 15
})

traffic_customer_data = pd.DataFrame({
    'hour': list(range(9, 24)),
    '访客': [0.0] * 15,
    '顾客': [0.0] * 15,
    '访客_text': [''] * 15,
    '顾客_text': [''] * 15
})

conv_data = pd.DataFrame({'hour': list(range(9, 24)), 'conversion': [0.0] * 15})
atv_data = pd.DataFrame({'hour': list(range(9, 24)), 'atv': [0.0] * 15})
hourly_completion_rate = pd.DataFrame({
    'hour': list(range(9, 24)),
    '小时完成率(%)': [0.0] * 15,
    '小时完成率_text': [''] * 15
})

df_raw = None
store_list = ["请选择"]
date_list = []
channel_list = ["全部渠道", "Online", "Offline"]
refresh_lock = threading.Lock()


# ======================
# 工具函数【完全原样不动】
# ======================
def clean_sales_series(series):
    return series.astype(str).str.replace(',', '').str.strip().apply(pd.to_numeric, errors='coerce').fillna(0.0)


# ======================
# ✅ 修复：百分比自动识别（1.01 → 101%，98% → 98%）
# 兼容未来API所有格式
# ======================
def clean_goal_index(value):
    try:
        s = str(value).strip()
        if "%" in s:
            return float(s.replace("%", "").strip())
        f = float(s)
        if f < 10:  # 小数格式（0.95 / 1.01）
            return f * 100
        return f
    except:
        return 0.0


def clean_cvr_series(series):
    return series.astype(str).str.replace('%', '').str.strip().apply(pd.to_numeric, errors='coerce').fillna(0.0)


def format_sales_to_k(value):
    if pd.isna(value) or value is None or value <= 0:
        return ''
    try:
        return f"{int(value / 1000)}k"
    except:
        return ""


def compute_hourly_net(df_group, col='sales'):
    if len(df_group) == 0:
        return pd.DataFrame({'hour': [], col: []})
    df_sorted = df_group.sort_values('hour')
    vals = df_sorted[col].tolist()
    hours = df_sorted['hour'].tolist()
    net = []
    prev = 0
    for i, val in enumerate(vals):
        net_val = max(val - prev, 0) if i > 0 else val
        net.append(net_val)
        prev = val
    return pd.DataFrame({'hour': hours, col: net})


# ======================
# Holt预测【完全原样不动】
# ======================
def predict_hourly_sales(df_all, store_id, target_date_str, channel):
    try:
        target_date = datetime.strptime(target_date_str, '%Y-%m-%d')
        weekday = target_date.weekday()

        history_dates = []
        for w in range(1, 5):
            d = target_date - timedelta(days=7 * w)
            history_dates.append(d.strftime('%Y-%m-%d'))

        hist = df_all[
            (df_all['store_id'] == store_id) &
            (df_all['date'].isin(history_dates)) &
            (df_all['channel'] == channel)
            ].copy()

        hours = list(range(9, 24))
        pred = {h: 0.0 for h in hours}
        if hist.empty:
            return pred

        hour_mean = hist.groupby('hour')['sales'].mean().reindex(hours).fillna(0)
        daily_totals = hist.groupby('date')['sales'].last().sort_index()
        if len(daily_totals) == 0:
            for h in hours:
                pred[h] = hour_mean.get(h, 0)
            return pred

        alpha = 0.7
        beta = 0.3
        if len(daily_totals) < 2:
            smooth_total = daily_totals.iloc[0]
        else:
            level = daily_totals.iloc[0]
            trend = daily_totals.iloc[1] - daily_totals.iloc[0]
            for val in daily_totals[1:]:
                new_level = alpha * val + (1 - alpha) * (level + trend)
                new_trend = beta * (new_level - level) + (1 - beta) * trend
                level, trend = new_level, new_trend
            smooth_total = level + trend

        total_mean_val = hour_mean.iloc[-1] if len(hour_mean) > 0 else 1
        total_mean_val = max(total_mean_val, 1)

        for h in hours:
            raw_val = hour_mean.get(h, 0)
            pred_h = raw_val * (smooth_total / total_mean_val)
            pred[h] = max(round(pred_h, 2), 0)

        return pred

    except Exception as e:
        print("预测异常:", e)
        return {h: 0.0 for h in range(9, 24)}


# ======================
# CSV刷新【完全原样无报错】
# ======================
def refresh_csv_data():
    global df_raw, store_list, date_list

    with refresh_lock:
        try:
            required_cols = [
                'StoreNo', 'Date', 'Time', 'totalStoreTraffic',
                'salesSummary_omniSales', 'salesSummary_onlineSales', 'salesSummary_offlineSales',
                'salesSummary_omniGoal', 'salesSummary_onlineGoal', 'salesSummary_offlineGoal',
                'salesSummary_omniIndexToGoal', 'salesSummary_onlineIndexToGoal', 'salesSummary_offlineIndexToGoal',
                'salesAndTickets_salesCVR', 'salesAndTickets_salesATV',
                'salesAndTickets_onlineSalesATV', 'salesAndTickets_offlineSalesATV',
                'salesAndTickets_offlineSalesTickets'
            ]

            df = pd.read_csv(
                CSV_PATH, encoding='utf-8', on_bad_lines='skip',
                usecols=required_cols, dtype={'StoreNo': str}
            )

            df['store_id'] = df['StoreNo'].astype(str).str.strip()
            df['date'] = pd.to_datetime(df['Date'], errors='coerce').dt.strftime('%Y-%m-%d')
            df = df[df['date'].notnull()]
            df['hour'] = df['Time'].str.split(':').str[0].astype(int, errors='ignore').fillna(9)
            df = df[df['hour'].between(9, 23)]
            df = df.drop_duplicates(subset=['store_id', 'date', 'hour'], keep='last')

            df['total_sales'] = clean_sales_series(df['salesSummary_omniSales'])
            df['online_sales'] = clean_sales_series(df['salesSummary_onlineSales'])
            df['offline_sales'] = clean_sales_series(df['salesSummary_offlineSales'])

            df['total_goal'] = clean_sales_series(df['salesSummary_omniGoal'])
            df['conversion'] = clean_cvr_series(df['salesAndTickets_salesCVR'])
            df['total_atv'] = clean_sales_series(df['salesAndTickets_salesATV'])
            df['total_traffic'] = clean_sales_series(df['totalStoreTraffic'])
            df['offline_tickets'] = clean_sales_series(df['salesAndTickets_offlineSalesTickets'])

            df_all = df[['store_id', 'date', 'hour', 'total_sales', 'conversion', 'total_atv', 'total_traffic',
                         'offline_tickets', 'total_goal', 'salesSummary_omniIndexToGoal']].copy()
            df_all['channel'] = '全部渠道'
            df_all.columns = ['store_id', 'date', 'hour', 'sales', 'conversion', 'atv', 'traffic', 'customer', 'goal',
                              'goal_index', 'channel']

            df_online = df[['store_id', 'date', 'hour', 'online_sales']].copy()
            df_online['conversion'] = 0
            df_online['atv'] = clean_sales_series(df['salesAndTickets_onlineSalesATV'])
            df_online['traffic'] = 0
            df_online['customer'] = 0
            df_online['goal'] = clean_sales_series(df['salesSummary_onlineGoal'])
            df_online['goal_index'] = df['salesSummary_onlineIndexToGoal']
            df_online['channel'] = 'Online'
            df_online.columns = ['store_id', 'date', 'hour', 'sales', 'conversion', 'atv', 'traffic', 'customer',
                                 'goal', 'goal_index', 'channel']

            df_offline = df[['store_id', 'date', 'hour', 'offline_sales']].copy()
            df_offline['conversion'] = 0
            df_offline['atv'] = clean_sales_series(df['salesAndTickets_offlineSalesATV'])
            df_offline['traffic'] = 0
            df_offline['customer'] = df['offline_tickets']
            df_offline['goal'] = clean_sales_series(df['salesSummary_offlineGoal'])
            df_offline['goal_index'] = df['salesSummary_offlineIndexToGoal']
            df_offline['channel'] = 'Offline'
            df_offline.columns = ['store_id', 'date', 'hour', 'sales', 'conversion', 'atv', 'traffic', 'customer',
                                  'goal', 'goal_index', 'channel']

            df_raw = pd.concat([df_all, df_online, df_offline], ignore_index=True)
            store_list = ["请选择"] + sorted(df_raw['store_id'].unique().tolist())
            date_list = sorted(df_raw['date'].unique().tolist())

            print(f"✅ CSV自动刷新完成：{len(df):,} 行 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        except Exception as e:
            print(f"❌ CSV刷新失败：{e}")


def auto_refresh_thread():
    while True:
        time.sleep(600)
        refresh_csv_data()


# ======================
# 筛选逻辑【只修复customer + 强制转整数，其余完全不动】
# ======================
def filter_data(state: State):
    try:
        if df_raw is None:
            return

        if state.sel_store == "请选择" and len(store_list) > 1:
            state.sel_store = store_list[1]
        if state.sel_date == None and len(date_list) > 0:
            state.sel_date = datetime.strptime(date_list[-1], '%Y-%m-%d')
        if state.sel_channel == None:
            state.sel_channel = "全部渠道"

        if state.sel_store == "请选择" or state.sel_date == None:
            return

        selected_date_str = state.sel_date.strftime('%Y-%m-%d')
        today_str = datetime.now().strftime('%Y-%m-%d')
        current_hour = datetime.now().hour
        hour_full = list(range(9, 24))
        hour_df = pd.DataFrame({'hour': hour_full})

        sales_data = df_raw[
            (df_raw['store_id'] == state.sel_store) &
            (df_raw['date'] == selected_date_str) &
            (df_raw['channel'] == state.sel_channel)
            ].copy()
        max_h = sales_data['hour'].max() if not sales_data.empty else 23
        sales_net = compute_hourly_net(sales_data)
        store_sales = hour_df.merge(sales_net, on='hour', how='left').fillna(0)

        if selected_date_str == today_str:
            store_sales.loc[store_sales['hour'] > current_hour, 'sales'] = None
        store_sales.loc[store_sales['hour'] < 10, 'sales'] = None
        store_sales = store_sales.rename(columns={'sales': '门店销售'})
        store_sales['门店销售_text'] = store_sales['门店销售'].apply(format_sales_to_k)

        store_b_sales = [None] * 15
        store_b_text = [''] * 15
        if state.sel_store_b not in ["请选择", None]:
            sales_data_b = df_raw[
                (df_raw['store_id'] == state.sel_store_b) &
                (df_raw['date'] == selected_date_str) &
                (df_raw['channel'] == state.sel_channel)
            ].copy()
            sales_net_b = compute_hourly_net(sales_data_b)
            store_b_df = hour_df.merge(sales_net_b, on='hour', how='left').fillna(0)
            if selected_date_str == today_str:
                store_b_df.loc[store_b_df['hour'] > current_hour, 'sales'] = None
            store_b_df.loc[store_b_df['hour'] < 10, 'sales'] = None
            store_b_sales = store_b_df['sales'].tolist()
            store_b_text = [format_sales_to_k(x) for x in store_b_sales]

        state.sales_dual_data = pd.DataFrame({
            'hour': hour_full,
            '门店销售': store_sales['门店销售'].tolist(),
            '对比门店销售': store_b_sales,
            '门店销售_text': store_sales['门店销售_text'].tolist(),
            '对比门店销售_text': store_b_text
        })

        full_channel_data = df_raw[
            (df_raw['store_id'] == state.sel_store) &
            (df_raw['date'] == selected_date_str) &
            (df_raw['channel'] == '全部渠道')
            ].copy()

        # ======================
        # ✅ 修复1：这里明确传入 col 名称，防止customer报错
        # ======================
        traffic_net = compute_hourly_net(full_channel_data, col='traffic')
        customer_net = compute_hourly_net(full_channel_data, col='customer')

        traffic_df = hour_df.merge(traffic_net, on='hour', how='left').fillna(0)
        customer_df = hour_df.merge(customer_net, on='hour', how='left').fillna(0)

        traffic_df.loc[(traffic_df['hour'] < 10) | (traffic_df['hour'] > max_h), 'traffic'] = None
        customer_df.loc[(customer_df['hour'] < 10) | (customer_df['hour'] > max_h), 'customer'] = None

        # ======================
        # ✅ 修复2：访客/顾客 强制转整数，不显示小数（人不能是小数）
        # ======================
        traffic_vals = []
        customer_vals = []
        traffic_text = []
        customer_text = []

        for t_val, c_val in zip(traffic_df['traffic'], customer_df['customer']):
            # 访客转整数
            if pd.isna(t_val):
                tv = None
            else:
                tv = int(round(t_val))

            # 顾客转整数
            if pd.isna(c_val):
                cv = None
            else:
                cv = int(round(c_val))

            traffic_vals.append(tv)
            customer_vals.append(cv)
            traffic_text.append(str(tv) if tv is not None else "")
            customer_text.append(str(cv) if cv is not None else "")

        state.traffic_customer_data = pd.DataFrame({
            'hour': hour_full,
            '访客': traffic_vals,
            '顾客': customer_vals,
            '访客_text': traffic_text,
            '顾客_text': customer_text
        })

        # 下面所有代码 100% 完全原样不动
        traffic_map = traffic_net.set_index('hour')['traffic'].to_dict()
        customer_map = customer_net.set_index('hour')['customer'].to_dict()
        sales_map = sales_net.set_index('hour')['sales'].to_dict()

        conv_vals = []
        atv_vals = []
        for h in hour_full:
            t = traffic_map.get(h, 0)
            c = customer_map.get(h, 0)
            s = sales_map.get(h, 0)

            if h >= 10 and h <= max_h and t > 0 and c > 0:
                conv_vals.append(round(c / t * 100, 2))
            else:
                conv_vals.append(None)

            if h >= 10 and h <= max_h and c > 0 and s > 0:
                atv_vals.append(round(s / c, 2))
            else:
                atv_vals.append(None)

        state.conv_data = pd.DataFrame({'hour': hour_full, 'conversion': conv_vals})
        state.atv_data = pd.DataFrame({'hour': hour_full, 'atv': atv_vals})

        hour_sales_map = dict(zip(sales_data['hour'], sales_data['sales'])) if not sales_data.empty else {}
        真实销售 = [None] * 15
        预测销售 = [None] * 15
        label = [''] * 15
        last_real_value = None

        for idx, h in enumerate(hour_full):
            if h < 10:
                continue
            val = hour_sales_map.get(h, None)
            真实销售[idx] = val
            label[idx] = format_sales_to_k(val) if val is not None else ''
            if val is not None:
                last_real_value = val

        if selected_date_str == today_str and last_real_value is not None:
            pred_dict = predict_hourly_sales(df_raw, state.sel_store, selected_date_str, state.sel_channel)
            for idx, h in enumerate(hour_full):
                if h == current_hour:
                    预测销售[idx] = last_real_value
                if h > current_hour and h >= 10:
                    pv = pred_dict.get(h, None)
                    预测销售[idx] = pv
                    label[idx] = format_sales_to_k(pv)

        state.forecast_two_color = pd.DataFrame({
            'hour': hour_full,
            '真实销售': 真实销售,
            '预测销售': 预测销售,
            'label': label
        })

        compl_list, compl_text = [], []
        goal_map = dict(zip(sales_data['hour'], sales_data['goal'])) if not sales_data.empty else {}
        net_map = dict(zip(sales_net['hour'], sales_net['sales'])) if not sales_net.empty else {}

        for h in hour_full:
            if h < 10 or h > max_h:
                compl_list.append(None)
                compl_text.append("")
            else:
                n = net_map.get(h, 0.0)
                g = goal_map.get(h, 1.0)
                r = round((n / g) * 100, 1) if g > 0 else 0.0
                compl_list.append(r)
                compl_text.append(f"{r}%")

        state.hourly_completion_rate = pd.DataFrame({
            'hour': hour_full,
            '小时完成率(%)': compl_list,
            '小时完成率_text': compl_text
        })

        current_sales = 0.0
        current_target = 0.0
        current_visitors = 0.0
        current_rate_val = 0.0

        if not sales_data.empty:
            last = sales_data.sort_values('hour').iloc[-1]
            current_sales = float(last['sales']) if not pd.isna(last['sales']) else 0.0
            current_target = float(last['goal']) if not pd.isna(last['goal']) else 0.0
            current_rate_val = clean_goal_index(last['goal_index'])

        if not full_channel_data.empty:
            last_v = full_channel_data.sort_values('hour').iloc[-1]
            current_visitors = int(round(float(last_v['traffic']))) if not pd.isna(last_v['traffic']) else 0

        state.total_sales = int(round(current_sales))
        state.sales_target = int(round(current_target))
        state.total_visitors = current_visitors
        state.completion_rate = f"{round(current_rate_val, 1)}%"

    except Exception as e:
        print(f"❌ 筛选错误：{e}")


# ======================
# 页面 100% 完全原样
# ======================
page = """
<|container|

# 🚀 Sales Daily Pulse Pro

<|layout|columns=1fr 1fr 1fr 1fr|gap=16px|
<|
<small>🏪 门店</small>
<|{sel_store}|selector|lov={store_list}|on_change=filter_data|dropdown|search|width=100%|>
|>
<|
<small>🏪 对比门店</small>
<|{sel_store_b}|selector|lov={store_list}|on_change=filter_data|dropdown|search|width=100%|>
|>
<|
<small>📅 日期</small>
<|{sel_date}|date|on_change=filter_data|width=100%|>
|>
<|
<small>📦 渠道</small>
<|{sel_channel}|selector|lov={channel_list}|on_change=filter_data|dropdown|width=100%|>
|>
|>

<|part|mt=24px|
**📈 销售额趋势**

<|layout|columns=1fr 1fr 1fr 1fr|gap=16px|
<|part|
**总销售额**
<|{total_sales}|>
|>
<|part|
**销售目标**
<|{sales_target}|>
|>
<|part|
**完成率**
<|{completion_rate}|>
|>
<|part|
**访客数**
<|{total_visitors}|>
|>
|>

<|{sales_dual_data}|chart|x=hour|y[1]=门店销售|y[2]=对比门店销售|text[1]=门店销售_text|text[2]=对比门店销售_text|type=line|line_shape=spline|mode=lines+markers+text|line_width[1]=4|line_width[2]=4|color[1]=#00d8ff|color[2]=#ff6b81|height=420px|>
|>

<|part|mt=4|
**📊 当日累计销售走势（真实+预测）**
<|{forecast_two_color}|chart|x=hour|y[1]=真实销售|y[2]=预测销售|text[1]=label|text[2]=label|type=line|line_shape=spline|mode=lines+markers+text|line_width[1]=4|line_width[2]=4|color[1]=#00d8ff|color[2]=#ff9100|height=400px|>
|>

<|part|mt=4|
**📊 小时完成率趋势**
<|{hourly_completion_rate}|chart|x=hour|y[1]=小时完成率(%)|text[1]=小时完成率_text|type=line|line_shape=spline|mode=lines+markers+text|line_width=4|color[1]=#00ff9d|height=360px|>
|>

<|part|mt=4|
**👥 访客 & 顾客趋势**
<|{traffic_customer_data}|chart|x=hour|y[1]=访客|y[2]=顾客|text[1]=访客_text|text[2]=顾客_text|type=line|line_shape=spline|mode=lines+markers+text|line_width[1]=4|line_width[2]=4|color[1]=#bf7af7|color[2]=#ff6b81|height=400px|>
|>

<|layout|columns=1fr 1|gap=20px|mt=4|
<|part|
**🎯 时段转化率**
<|{conv_data}|chart|x=hour|y=conversion|type=line|line_shape=spline|line_width=4|color=#ff55aa|height=360px|>
|>
<|part|
**💰 时段客单价**
<|{atv_data}|chart|x=hour|y=atv|type=line|line_shape=spline|line_width=4|color=#22ddaa|height=360px|>
|>
|>

|>

<|
<style>
body {
    background: linear-gradient(135deg, #020108 0%, #0a1028 100%);
    color: #e8ff8;
    padding: 2rem;
}
.taipy-chart {
    background: rgba(22, 33, 66, 0.7);
    border-radius: 20px;
    padding: 20px;
    box-shadow: 0 0 25px rgba(0, 140, 255, 0.2);
    margin-top: 8px;
}
.taipy-selector, .taipy-date {
    background: rgba(30, 50, 100, 0.8);
    border-radius: 12px;
    color: #fff !important;
}
small {
    font-size: 14px;
    opacity: 0.9;
}
h1 {
    font-size: 42px;
    color: #00d8ff;
    text-align: center;
    text-shadow: 0 0 15px rgba(0, 200, 255, 0.7);
}
strong {
    font-size: 18px;
    color: #72d8ff;
}
</style>
|>
"""

if __name__ == "__main__":
    refresh_csv_data()
    threading.Thread(target=auto_refresh_thread, daemon=True).start()
    gui = Gui(page)
    gui.run(host="0.0.0.0", port=8088, use_reloader=False, title="SalesDailyPulse Pro")