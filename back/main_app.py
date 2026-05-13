import requests
import json
import csv
import glob
import logging
import time
from datetime import datetime
from pathlib import Path
import os # Added for os.path.splitext, os.path.basename

try:
    import msvcrt
except ImportError:
    msvcrt = None

# ================= 配置区域 =================
BASE_URL = "https://spica-tianji.internal.ingka-dt.cn/SelfServeDP-api/realtime/anonymity-report/store/sales/summary?key="
# 新增的流量数据API地址
TRAFFIC_BASE_URL = "https://spica-tianji.internal.ingka-dt.cn/SelfServeDP-api/realtime/anonymity-report/store/sales/list?key="

storeName = ["天津店","无锡店","北京西红门","北京五棵松PUP","温州PUP","重庆店","武汉店","杭州店","成都成华店",
"西安一店","广州佛山店","成都高新店","南京店","苏州店","大连店","济南店","郑州店","长沙店",
"广州天河店","青岛店","昆明店","福州店","南宁店","西安二店","上海临空店","合肥店","北京四元桥店",
"深圳店","上海徐汇店","上海北蔡店","沈阳店","东莞"]

storeNo = ["058", "164", "214", "21401", "27901", "330", "340", "401", "418", "424", 
"459", "466", "481", "484", "495", "521", "572", "581", "584", "601", "621", "624", 
"630", "667", "672", "673", "802", "833", "856", "885", "886", "1279"
]

key = ["16c4aafd",
        "f21c3a1c",
        "c8634be4",
        "74bac773",
        "8f73fa24",
        "692291e1",
        "c2537687",
        "ae785528",
        "12baa5da",
        "ea5bb70d",
        "60e22403",
        "0859243a",
        "875ffee5",
        "b07ace33",
        "4628aa91",
        "88742259",
        "57cb00d6",
        "42883aff",
        "e34fd9a1",
        "f13c9c03",
        "16f1149d",
        "5ac1376c",
        "c84c0d09",
        "ac632cb7",
        "dd0002b5",
        "c4dccec4",
        "8e085143",
        "d363bf27",
        "65e8422a",
        "3146be89",
        "a5fb3114",
        "cbb865d1",
        
]

# 字典格式: {storeName: {storeNo: key}}
STORES = {}
for name, no, k in zip(storeName, storeNo, key):
    STORES[name] = {no: k}
# ===========================================

# --- Configuration for paths ---
# CONFIG_FILE = "config.json" # Removed: config file path is now dynamic
DEFAULT_JSON_OUTPUT_DIR = 'output'
DEFAULT_CSV_REPORT_DIR = 'report'
REPORT_CSV_FILENAME = 'report.csv'
LOG_DIR = 'logs' # New constant for log directory

def get_config_file_path() -> Path:
    """
    Determines the appropriate, user-writable path for config.json.
    On Windows, uses %APPDATA%/SDT2.0-Hourly/.
    On other OS, uses ~/.sdt2_0_hourly/.
    """
    if os.name == 'nt': # Windows
        app_data_path = Path(os.getenv('APPDATA'))
        config_dir = app_data_path / "SDT2.0-Hourly" # A specific folder for the app
    else: # Linux/macOS or other
        config_dir = Path.home() / ".sdt2_0_hourly" # Hidden folder in home directory

    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "config.json"

def setup_logging(log_dir: Path):
    """Configures logging to file and console."""
    log_dir.mkdir(parents=True, exist_ok=True)
    log_filename = log_dir / f"app_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    # Get the root logger
    logger = logging.getLogger()
    logger.setLevel(logging.INFO) # Capture INFO and above

    # Clear existing handlers to prevent duplicate output if called multiple times
    if logger.hasHandlers():
        logger.handlers.clear()

    # Create a formatter
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    # File handler
    file_handler = logging.FileHandler(log_filename, encoding='utf-8')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    logging.info(f"Logging started. Output will be saved to {log_filename}")

def get_all_paths():
    """
    从配置文件中获取JSON输出路径和CSV报告路径，如果找不到则提示用户。
    为将来的运行记住路径。
    Returns: (json_output_path_obj, csv_report_path_obj)
    """
    config_path = get_config_file_path() # Correctly get the config file path
    
    json_output_path = None # Will store Path objects
    csv_report_path = None

    # 1. 尝试从配置文件读取
    if config_path.exists():
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                json_output_path_str = config.get("json_output_path", "")
                csv_report_path_str = config.get("csv_report_path", "")

                # 检查路径是否存在且有效
                if json_output_path_str and Path(json_output_path_str).exists() and \
                   csv_report_path_str and Path(csv_report_path_str).exists():
                    json_output_path = Path(json_output_path_str)
                    csv_report_path = Path(csv_report_path_str)
                    print(f"已记住的JSON输出路径: {json_output_path}")
                    print(f"已记住的CSV报告路径: {csv_report_path}")
                    logging.info(f"已记住的JSON输出路径: {json_output_path}")
                    logging.info(f"已记住的CSV报告路径: {csv_report_path}")
                    return json_output_path, csv_report_path
        except (json.JSONDecodeError, IOError, TypeError) as e: # Added TypeError for potential issues with Path conversion
            logging.warning(f"读取配置文件 '{config_path.name}' 时出错: {e}。将提示输入新路径。")

    # 2. 如果路径未找到或无效，则提示用户输入或使用默认值
    print("\n--- 路径配置 ---")
    logging.info("--- 路径配置 ---")

    # Use timed_input_check to decide if user wants to manually input paths
    if timed_input_check(timeout=10, prompt_message=">>> 如需手动输入JSON和CSV路径，请在倒计时结束前按 'Enter' 键..."):
        # User pressed Enter, proceed with manual input
        while True:
            user_input_json = input(f"请输入JSON文件保存的文件夹路径 (默认为 '{DEFAULT_JSON_OUTPUT_DIR}')，然后按回车: ").strip()
            if not user_input_json:
                user_input_json = DEFAULT_JSON_OUTPUT_DIR
            
            try:
                json_output_path = Path(user_input_json)
                json_output_path.mkdir(parents=True, exist_ok=True) # 尝试创建目录以验证路径
                break
            except Exception as e:
                print(f"创建或访问JSON输出路径 '{user_input_json}' 时出错: {e}\n请确保您有权限，并输入一个有效的 Windows 路径。")
                logging.error(f"创建或访问JSON输出路径 '{user_input_json}' 时出错: {e}\n请确保您有权限，并输入一个有效的 Windows 路径。")

        while True:
            user_input_csv = input(f"请输入CSV报告文件保存的文件夹路径 (默认为 '{DEFAULT_CSV_REPORT_DIR}')，然后按回车: ").strip()
            if not user_input_csv:
                user_input_csv = DEFAULT_CSV_REPORT_DIR

            try:
                csv_report_path = Path(user_input_csv)
                csv_report_path.mkdir(parents=True, exist_ok=True) # 尝试创建目录以验证路径
                break
            except Exception as e:
                print(f"创建或访问CSV报告路径 '{user_input_csv}' 时出错: {e}\n请确保您有权限，并输入一个有效的 Windows 路径。")
                logging.error(f"创建或访问CSV报告路径 '{user_input_csv}' 时出错: {e}\n请确保您有权限，并输入一个有效的 Windows 路径。")
        
        print("已获取用户输入的路径。")
        logging.info("已获取用户输入的路径。")

        print(f"JSON输出路径将设置为: {json_output_path.absolute()}")
        print(f"CSV报告路径将设置为: {csv_report_path.absolute()}")
    else:
        # Timeout occurred or non-Windows, use default paths
        json_output_path = Path(DEFAULT_JSON_OUTPUT_DIR)
        csv_report_path = Path(DEFAULT_CSV_REPORT_DIR)
        
        try:
            json_output_path.mkdir(parents=True, exist_ok=True)
            csv_report_path.mkdir(parents=True, exist_ok=True)
            print(f"倒计时结束，自动使用默认JSON输出路径: {json_output_path.absolute()}")
            print(f"自动使用默认CSV报告路径: {csv_report_path.absolute()}")
            logging.info(f"倒计时结束，自动使用默认JSON输出路径: {json_output_path.absolute()}")
            logging.info(f"自动使用默认CSV报告路径: {csv_report_path.absolute()}")
        except Exception as e:
            print(f"创建默认路径时出错: {e}")
            logging.error(f"创建默认路径时出错: {e}")
            raise # Re-raise if default paths cannot be created

    # 3. 将有效路径保存到配置文件
    try:
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump({
                "json_output_path": str(json_output_path.absolute()),
                "csv_report_path": str(csv_report_path.absolute())
            }, f, indent=4)
        logging.info(f"路径已保存到 '{config_path.name}'。")
    except IOError as e: # CONFIG_FILE is now config_path.name for logging clarity
        print(f"保存配置文件 '{config_path.name}' 时出错: {e}")
        logging.error(f"保存配置文件 '{config_path.name}' 时出错: {e}")
        
    return json_output_path, csv_report_path

def timed_input_check(timeout=10, prompt_message=""):
    """
    等待用户按 Enter 键进入管理模式或取消自动执行，否则超时返回 False。
    仅在 Windows 下有效 (依赖 msvcrt)。
    """
    if not msvcrt:
        print("非 Windows 环境，跳过倒计时等待。")
        logging.info("非 Windows 环境，跳过倒计时等待。")
        return False
        
    print(f"\n系统将在 {timeout} 秒后自动执行。")
    print(prompt_message)
    
    logging.info(f"\n系统将在 {timeout} 秒后自动执行。")
    logging.info(prompt_message)
    start_time = time.time()
    while (time.time() - start_time) < timeout:
        if msvcrt.kbhit():
            ch = msvcrt.getch()
            if ch == b'\r':
                print("\n已检测到输入。")
                logging.info("\n已检测到输入。")
                return True
        time.sleep(0.1)
    
    logging.info("\n倒计时结束，自动开始执行...")
    return False

def manage_data(names, nos, keys):
    """
    简单的命令行 CRUD 界面，用于管理店铺列表
    """
    while True:
        logging.info("\n" + "="*35)
        print("\n" + "="*35)
        print("       店铺数据管理模式")
        logging.info("="*35)
        print("1. [查看] 列出所有店铺")
        print("2. [添加] 新增店铺")
        print("3. [修改] 修改店铺信息")
        print("4. [删除] 删除店铺")
        print("5. [退出] 保存更改并运行任务")
        
        choice = input("\n请输入选项 (1-5): ").strip()
        
        if choice == '1':
            print(f"\n{'序号':<6}{'店名':<15}{'店号':<10}{'密钥'}")
            print("-" * 65)
            for i, (n, no, k) in enumerate(zip(names, nos, keys)):
                print(f"{i+1:<6}{n:<15}{no:<10}{k}")
                
        elif choice == '2':
            print("\n--- 新增店铺 ---")
            logging.info("\n--- 新增店铺 ---")
            n = input("请输入店名: ").strip()
            no = input("请输入店号: ").strip()
            k = input("请输入密钥: ").strip()
            if n and no and k:
                names.append(n)
                nos.append(no)
                keys.append(k)
                print("✅ 添加成功!")
            else:
                logging.warning("❌ 信息不完整，添加失败。")
                print("❌ 信息不完整，添加失败。")
        elif choice == '3':
            idx = input("请输入要修改的序号: ").strip()
            if idx.isdigit() and 1 <= int(idx) <= len(names):
                i = int(idx) - 1
                print(f"当前选中: {names[i]} (No.{nos[i]})")
                logging.info(f"当前选中: {names[i]} (No.{nos[i]})")
                names[i] = input(f"新店名 (回车保留 '{names[i]}'): ").strip() or names[i]
                nos[i] = input(f"新店号 (回车保留 '{nos[i]}'): ").strip() or nos[i]
                keys[i] = input(f"新密钥 (回车保留原值): ").strip() or keys[i]
                print("✅ 修改成功!")
            else:
                print("❌ 无效的序号。")
        
        elif choice == '4':
            idx = input("请输入要删除的序号: ").strip()
            if idx.isdigit() and 1 <= int(idx) <= len(names):
                i = int(idx) - 1
                confirm = input(f"⚠️ 确认删除 {names[i]}? (y/n): ").lower()
                if confirm == 'y':
                    del names[i]
                    del nos[i]
                    del keys[i]
                    print("✅ 删除成功!")
        
        elif choice == '5':
            break

def download_rts_data(output_dir: Path):
    """
    核心逻辑：遍历字典，下载并保存 JSON 文件
    """
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 开始下载JSON数据...")
    
    # 获取统一的时间戳用于本次批次 (格式: yyyymmdd-hhmm)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M")

    # 2. 遍历字典进行下载
    for store_name, store_info in STORES.items():
        for store_no, key_val in store_info.items(): # Renamed 'key' to 'key_val' to avoid conflict with global 'key' list
            # --- 第一个 API 请求 (summary) ---
            summary_full_url = f"{BASE_URL}{key_val}"
            print(f"正在请求 Summary 数据: {store_name} (No.{store_no})...")
            logging.info(f"正在请求 Summary 数据: {store_name} (No.{store_no})...")

            new_json = {} # Initialize new_json for each store

            try:
                # 发送 HTTP GET 请求 (设置10秒超时防止卡死)
                response = requests.get(summary_full_url, timeout=10)
                response.raise_for_status() # 如果状态码不是200，抛出异常
                
                # 1. 解析 JSON
                summary_data = response.json().get('data', {})
                new_json.update(summary_data) # Add summary data to new_json
                print(f"成功获取 Summary 数据: {store_name}")
                logging.info(f"成功获取 Summary 数据: {store_name}")
                
                # 2. 删除 foodSales 中的指定 null 值字段
                if 'foodSales' in new_json and isinstance(new_json.get('foodSales'), dict):
                    keys_to_delete = [
                        "offlineSales", "offlineGoal", "offlineIndexToGoal",
                        "onlineSales", "onlineGoal", "onlineIndexToGoal"
                    ]
                    for key_to_del in keys_to_delete:
                        # 使用 pop 并提供默认值 None，可以安全地删除键，即使它不存在
                        new_json['foodSales'].pop(key_to_del, None)

            except requests.exceptions.JSONDecodeError:
                print(f"解析 Summary JSON 失败。服务器返回原始内容: [{response.text}]")
                logging.error(f"解析 Summary JSON 失败。服务器返回原始内容: [{response.text}]")
                continue # Skip to next store if summary data fails
            except Exception as e:
                print(f"请求 Summary 数据失败: {store_name} (No.{store_no}) - {str(e)}")
                logging.error(f"请求 Summary 数据失败: {store_name} (No.{store_no}) - {str(e)}")
                continue # Skip to next store if summary data fails

            # --- 第二个 API 请求 (totalStoreTraffic) ---
            traffic_full_url = f"{TRAFFIC_BASE_URL}{key_val}"
            print(f"正在请求 Traffic 数据: {store_name} (No.{store_no})...")
            logging.info(f"正在请求 Traffic 数据: {store_name} (No.{store_no})...")

            try:
                traffic_response = requests.get(traffic_full_url, timeout=10)
                traffic_response.raise_for_status()
                traffic_response_json = traffic_response.json()

                # 假设 totalStoreTraffic 在 'data' 字段下，且 'data' 可能是一个列表或字典
                # 如果 'data' 是一个列表，我们尝试获取第一个元素的 'totalStoreTraffic'
                # 如果 'data' 是一个字典，我们直接获取 'totalStoreTraffic'
                total_store_traffic = None
                data_field = traffic_response_json.get('data')

                if isinstance(data_field, list) and data_field:
                    # Assuming totalStoreTraffic is in the first item of the list
                    total_store_traffic = data_field[0].get('totalStoreTraffic')
                elif isinstance(data_field, dict):
                    total_store_traffic = data_field.get('totalStoreTraffic')
                
                if total_store_traffic is not None:
                    new_json['totalStoreTraffic'] = total_store_traffic
                    print(f"成功获取 Traffic 数据 (totalStoreTraffic: {total_store_traffic}): {store_name}")
                    logging.info(f"成功获取 Traffic 数据 (totalStoreTraffic: {total_store_traffic}): {store_name}")
                else:
                    print(f"Traffic 数据中未找到 'totalStoreTraffic' 字段或数据为空: {store_name}")
                    logging.warning(f"Traffic 数据中未找到 'totalStoreTraffic' 字段或数据为空: {store_name}")
                    new_json['totalStoreTraffic'] = None # Ensure the key exists even if value is null

            except requests.exceptions.JSONDecodeError:
                print(f"解析 Traffic JSON 失败。服务器返回原始内容: [{traffic_response.text}]")
                logging.error(f"解析 Traffic JSON 失败。服务器返回原始内容: [{traffic_response.text}]")
                new_json['totalStoreTraffic'] = None # Ensure the key exists even if value is null
            except Exception as e:
                print(f"请求 Traffic 数据失败: {store_name} (No.{store_no}) - {str(e)}")
                logging.error(f"请求 Traffic 数据失败: {store_name} (No.{store_no}) - {str(e)}")
                new_json['totalStoreTraffic'] = None # Ensure the key exists even if value is null

            # --- 保存合并后的 JSON 文件 ---
                # 构造文件名: storeName_storeno_yyyymmdd-hhmm.json
            filename = f"{store_name}_{store_no}_{timestamp}.json"
            file_path = output_dir / filename

            print(f"尝试保存JSON文件到: {file_path.absolute()}")

            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(new_json, f, ensure_ascii=False, indent=4)

                print(f"成功: 已保存 {filename}")
                logging.info(f"成功: 已保存 {filename}")
            except Exception as e:
                print(f"保存文件 {filename} 失败: {str(e)}")
                logging.error(f"保存文件 {filename} 失败: {str(e)}")

    print(f"[{datetime.now().strftime('%H:%M:%S')}] JSON数据下载完成。")
    logging.info("JSON数据下载完成。")


# --- CSV Export Functions (from json_to_csv.py) ---

def parse_filename(filename):
    """
    Parses filename to extract metadata.
    Expected format: storeName_storeno_yyyymmdd-hhmm.json
    Returns: store_name, store_no, date_str (yyyy/mm/dd), time_str (hh:00)
    """
    base_name = os.path.splitext(filename)[0]
    # Split from right to handle potential underscores in storeName
    parts = base_name.rsplit('_', 2)
    
    if len(parts) != 3:
        return None
    
    store_name = parts[0]
    store_no = parts[1]
    datetime_part = parts[2] # yyyymmdd-hhmm
    
    # Validation and type conversion
    # Ensure store_no is always a string for consistency in data processing
    store_no = str(store_no)

    # Parse datetime part
    if '-' not in datetime_part:
        return None
    
    date_raw, time_raw = datetime_part.split('-')
    
    # Format Date: yyyymmdd -> yyyy/mm/dd
    if len(date_raw) == 8:
        date_formatted = f"{date_raw[:4]}/{date_raw[4:6]}/{date_raw[6:]}"
    else:
        date_formatted = date_raw
        
    # Format Time: hhmm -> hh:00 (Minutes forced to 00)
    if len(time_raw) >= 2:
        hour = time_raw[:2]
        time_formatted = f"{hour}:00"
    else:
        time_formatted = "00:00"

    return store_name, store_no, date_formatted, time_formatted

def get_existing_data(file_path: Path):
    """
    Reads existing CSV to get headers, max_id, a set of record signatures for deduplication,
    and all existing rows.
    Returns: (max_id, existing_fieldnames, existing_signatures, all_existing_rows)
    """
    if not file_path.exists():
        return 0, None, set(), [] # Return 0 for max_id if file doesn't exist
        
    signatures = set()
    max_id = 0
    headers = None
    all_existing_rows = [] # New: to store all existing rows

    with open(file_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames
        
        if not headers:
            return 0, None, set(), [] # Return 0 for max_id if no headers
            
        # Identify columns to use for signature (all except Seq)
        sig_keys = [k for k in headers if k != 'Seq']
        
        for row_dict in reader: # Renamed 'row' to 'row_dict' to avoid confusion with 'row' in export_to_csv
            # Convert Seq to int for comparison later and store it back
            all_existing_rows.append(row_dict) # Store the row
            # Track Max ID
            try:
                seq_val = int(row_dict.get('Seq', 0))
                row_dict['Seq'] = seq_val
            except ValueError:
                row_dict['Seq'] = 0 # Default to 0 if Seq is not a valid integer
            
            all_existing_rows.append(row_dict) # Store the row
            
            # Track Max ID from the integer 'Seq'
            if row_dict['Seq'] > max_id:
                max_id = row_dict['Seq']
            
            sig = tuple(str(row_dict.get(k, '')) for k in sig_keys) # Ensure values are strings for signature consistency

            signatures.add(sig)
            
    return max_id, headers, signatures, all_existing_rows # Return max_id
def flatten_data(data):
    """
    Flattens nested dictionaries in the data with key_subkey format.
    Example: {'a': {'b': 1}} -> {'a_b': 1}
    """
    flattened = {}
    for key, value in data.items():
        if isinstance(value, dict):
            for sub_key, sub_value in value.items():
                flattened[f"{key}_{sub_key}"] = sub_value
        else:
            flattened[key] = value
    return flattened

def transform_value(key, value): # Modified: Added 'key' parameter
    """
    Transforms values based on business rules:
    1. Keys containing 'IndexToGoal': Convert to Percentage.
    2. Strings ending in 'K': Strip K, *1000, format as Thousands Separator.
    3. Strings ending in 'M': Strip M, *1,000,000, format as Thousands Separator.
    4. Values < 1 (absolute, non-zero): Convert to Percentage.
    """
    # Rule 1: Keys containing 'IndexToGoal' should always be percentages
    if "IndexToGoal" in key or "CVR" in key:
        try:
            f_val = float(value)
            return "{:.1f}%".format(f_val * 100)
        except (ValueError, TypeError):
            # If conversion to float fails, return original value
            return value

    # Rule 1 & 2: Handle K and M values
    if isinstance(value, str):
        upper_val = value.upper()
        if upper_val.endswith('K'):
            try:
                num = float(value[:-1]) * 1000
                return "{:,.0f}".format(num)
            except ValueError:
                pass
        elif upper_val.endswith('M'):
            try:
                num = float(value[:-1]) * 1000000
                return "{:,.0f}".format(num)
            except ValueError:
                pass

    # Rule 4: Handle values < 1 (general percentage conversion)
    
    """
    try:
        f_val = float(value)
        if f_val != 0 and abs(f_val) < 1:
            return "{:.1f}%".format(f_val * 100)
    except (ValueError, TypeError):
        pass
    """    
    return value

def export_to_csv(json_input_dir: Path, csv_report_dir: Path):
    """
    Scans JSON files in json_input_dir and exports them to a CSV report.
    """
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 开始导出CSV报告...")
    logging.info("开始导出CSV报告...")

    report_csv_path = csv_report_dir / REPORT_CSV_FILENAME
    
    # Find JSON files
    if not json_input_dir.exists():
        print(f"JSON输入目录 '{json_input_dir}' 不存在。")
        logging.warning(f"JSON输入目录 '{json_input_dir}' 不存在。")
        return
        
    json_files = glob.glob(str(json_input_dir / '*.json'))
    # Sort to ensure consistent processing order
    json_files.sort()
    
    if not json_files:
        print("没有找到JSON文件可供处理。")
        logging.info("没有找到JSON文件可供处理。")
        return

    # Prepare for processing
    
    # Get max_id from existing data. This will be the starting point for new Seq IDs.
    max_existing_seq, existing_headers, _, all_existing_rows = get_existing_data(report_csv_path)
    
    current_new_seq_id = max_existing_seq + 1 # Start new Seq IDs from max_existing_seq + 1
    newly_processed_rows = [] # These are the new rows from JSON files
    all_json_data_keys = set() # Collects all dynamic keys from new JSONs

    # Process files to build data rows
    for json_file in json_files:
        filename = os.path.basename(json_file)
        meta = parse_filename(filename)
        
        if not meta:
            print(f"跳过无效文件名格式: {filename}")
            logging.warning(f"跳过无效文件名格式: {filename}")
            continue
            
        store_name, store_no, fmt_date, fmt_time = meta
        
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            print(f"读取 {filename} 时出错: {e}")
            logging.error(f"读取 {filename} 时出错: {e}")
            continue
            
        data = flatten_data(data) # This 'data' is the flattened version for the current JSON
        all_json_data_keys.update(data.keys()) # Update with keys from this JSON

        # Apply value transformations
        for k, v in data.items(): # Modified: Pass 'k' (key) to transform_value
            data[k] = transform_value(k, v)
            
        # Create a new row dictionary, without 'Seq' initially
        processed_row = {
            'StoreName': store_name,
            'StoreNo': str(store_no), # Ensure StoreNo is always a string
            'Date': fmt_date,
            'Time': fmt_time,
            'Seq': current_new_seq_id # Assign a temporary Seq to new rows
        }
        processed_row.update(data)
        newly_processed_rows.append(processed_row)
        current_new_seq_id += 1 # Increment for the next new row
        
    if not newly_processed_rows and not all_existing_rows:
        print("没有找到有效数据可供导出。")
        logging.info("没有找到有效数据可供导出。")
        return
    
    # Combine existing and newly processed rows.
    # The order is important for 'keep="last"': new data should come after old data.
    # all_existing_rows already have 'Seq' as int from get_existing_data.
    combined_rows = all_existing_rows + newly_processed_rows 

    # Apply deduplication logic (equivalent to df.drop_duplicates(subset=..., keep="last"))
    deduplication_subset_keys = ['StoreName', 'StoreNo', 'Date', 'Time']
    
    # Use a dictionary to store the best row for each signature
    # Key: tuple of (StoreName, StoreNo, Date, Time)
    # Value: the row dictionary with the highest 'Seq' encountered so far for that key
    best_rows_by_signature = {}
    
    for row in combined_rows:
        signature_parts = tuple(row.get(k, '') for k in deduplication_subset_keys)
        
        current_seq = row.get('Seq', 0) # Should always be present and int now
        
        if signature_parts not in best_rows_by_signature:
            best_rows_by_signature[signature_parts] = row
        else:
            # If a row with this signature already exists, compare their 'Seq' values
            existing_best_row = best_rows_by_signature[signature_parts]
            existing_seq = existing_best_row.get('Seq', 0) # Should always be present and int now
            
            if current_seq > existing_seq:
                # This new row has a larger Seq, so it becomes the new best
                best_rows_by_signature[signature_parts] = row
            # else: current_seq is not greater, keep the existing best row

    # Extract the deduplicated rows.
    # Sort them by Date, Time, StoreName, StoreNo for consistent output order.
    deduplicated_list_for_resequencing = sorted(
        best_rows_by_signature.values(),
        key=lambda x: (x.get('Date', ''), x.get('Time', ''), x.get('StoreName', ''), str(x.get('StoreNo', ''))) # Ensure StoreNo is string for sorting
    )

    final_rows_for_csv = []
    current_seq_id = 1
    for row in deduplicated_list_for_resequencing:
        row_copy = row.copy() # Make a copy to avoid modifying the original dict in best_rows_by_signature
        row_copy['Seq'] = current_seq_id
        final_rows_for_csv.append(row_copy)
        current_seq_id += 1

    if not final_rows_for_csv:
        print("经过去重后，没有找到有效数据可供导出。")
        logging.info("经过去重后，没有找到有效数据可供导出。")
        return
    
    # Determine the final set of fieldnames for the CSV
    base_fieldnames = ['Seq', 'StoreName', 'StoreNo', 'Date', 'Time']
    
    # Collect all keys from the final deduplicated rows to form the complete header
    all_keys_in_final_data = set()
    for row in final_rows_for_csv:
        all_keys_in_final_data.update(row.keys())

    dynamic_keys_from_data = sorted(list(all_keys_in_final_data - set(base_fieldnames)))
    final_fieldnames = base_fieldnames + dynamic_keys_from_data

    # Always rewrite the entire file after deduplication and re-sequencing
    mode = 'w'
    
    try:
        with open(report_csv_path, mode, newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=final_fieldnames, extrasaction='ignore')
            
            writer.writeheader() # Always write header when rewriting
            writer.writerows(final_rows_for_csv)
                
        print(f"成功写入 {len(final_rows_for_csv)} 条记录到 {report_csv_path} (已去重)。")
        logging.info(f"成功写入 {len(final_rows_for_csv)} 条记录到 {report_csv_path} (已去重)。")

    except IOError as e:
        print(f"写入CSV时出错: {e}")
        logging.error(f"写入CSV时出错: {e}")


    
    print(f"[{datetime.now().strftime('%H:%M:%S')}] CSV报告导出完成。")
    logging.info("CSV报告导出完成。")

    # 将所有处理过的JSON文件移动到历史目录
    history_dir = json_input_dir / "history"
    try:
        history_dir.mkdir(parents=True, exist_ok=True) # 确保历史目录存在
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 开始将JSON文件移动到历史目录 '{history_dir}'...")
        logging.info(f"开始将JSON文件移动到历史目录 '{history_dir}'...")

        for json_file_path_str in json_files:
            json_file_path = Path(json_file_path_str)
            destination_path = history_dir / json_file_path.name
            json_file_path.rename(destination_path) # 移动文件
            logging.info(f"已将 '{json_file_path.name}' 移动到 '{history_dir.name}'。")
        print(f"[{datetime.now().strftime('%H:%M:%S')}] JSON文件移动完成。")
        logging.info("JSON文件移动完成。")
    except Exception as e:
        print(f"移动JSON文件到历史目录失败: {e}")
        logging.error(f"移动JSON文件到历史目录失败: {e}")


if __name__ == "__main__":
    # Setup logging first
    log_path = Path(LOG_DIR)
    setup_logging(log_path)

    # 1. 程序启动前确保配置了所有路径 (如果配置文件存在则跳过，不存在则提示输入)
    json_output_dir, csv_report_dir = get_all_paths()

    # 2. 启动前检查是否按 Enter 进入店铺管理模式 (超时 10 秒)
    if timed_input_check(timeout=10, prompt_message=">>> 如需修改店铺信息(增删改查)，请在倒计时结束前按 'Enter' 键..."):
        manage_data(storeName, storeNo, key)
        # 如果用户修改了列表，需要重新构建 STORES 字典
        STORES.clear()
        for name, no, k in zip(storeName, storeNo, key):
            STORES[name] = {no: k}
            
    # 3. 下载 JSON 数据
    download_rts_data(json_output_dir)

    # 4. 检查是否需要等待用户输入以取消CSV导出 (超时 10 秒)
    if timed_input_check(timeout=10, prompt_message=">>> 如需取消CSV导出，请在倒计时结束前按 'Enter' 键..."):
        print("CSV 导出任务已取消。")
        logging.info("CSV 导出任务已取消。")
    else:
        # 5. 导出 CSV 报告
        export_to_csv(json_output_dir, csv_report_dir)

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 程序执行完毕。")
    logging.info("程序执行完毕。")
