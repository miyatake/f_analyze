import sys
import yaml
import os
import logging
from fortran_analyzer import FortranAnalyzer
from mermaid_generator import MermaidGenerator
from japanese_encoding import detect_encoding_and_read_file # 文字コード判別用
import json


# ログ設定
def setup_logging(log_filename: str):
    """
    ログ設定を構成し、コンソールに簡易ログ、ファイルに詳細ログを出力します。
    ログファイル 'fortran_analyzer_log.txt' は実行ごとに新しく作成されます。
    """
    # ルートロガーを取得
    logger = logging.getLogger('')
    
    # ルートロガーのハンドラをクリア（二重出力を防ぐため）
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)

    logger.setLevel(logging.DEBUG) # 全体としての最低レベル
    
    # ロガーを新しく取得し、設定を適用する
    # logging.basicConfig はルートロガーに設定を適用するため、
    # 複数回呼び出すと意図しない結果になることがあります。
    # ここではファイルハンドラとコンソールハンドラを明示的に設定します。
    logger = logging.getLogger('') # ルートロガーを取得
    logger.setLevel(logging.DEBUG)

    # --- ファイルハンドラの設定 ---
    file_handler = logging.FileHandler(log_filename, mode='w', encoding='utf-8')
    file_handler.setLevel(logging.DEBUG) # ファイルにはDEBUGレベル以上のすべてを出力
    file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)
    
    # --- コンソールハンドラの設定 ---
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO) # コンソールにはINFOレベル以上のみ出力
    console_formatter = logging.Formatter('%(levelname)s: %(message)s') # 簡易フォーマット
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # --- 重要: fortran_analyzerのロガーがルートロガーに伝播しないようにする ---
    # FortranAnalyzer内でログが出力される際、そのロガーが自身のハンドラと、
    # さらにルートロガーのハンドラにもメッセージを伝播するため重複が発生します。
    # analyzer_logger = logging.getLogger('FortranAnalyzer') # FortranAnalyzer内で使われているロガー名
    # analyzer_logger.propagate = False # ルートロガーへの伝播を停止

    # もしFortranAnalyzer内で専用のロガーインスタンスを使わず、
    # logging.info()のようにルートロガーを使っている場合はこの設定は不要です。
    # しかし、今回の重複出力の様子を見ると、FortranAnalyzerが独自のロガーを持ち、
    # そのロガーがルートロガーに伝播している可能性が高いです。
    # そのため、FortranAnalyzerの初期化時に、analyzerインスタンスのロガーの伝播を制御します。


# cntlファイルの読み込みに関する関数
# Windows11の右クリックで取得したパスはバックスラッシュが含まれるため、そのまま fortran_analyze.cntl に張り付けると「YAML形式」ではそのまま読み込めずエラーになる。
# よって入力ファイルに対しては、生テキストとして読み込み、YAML安全なファイルパスに変換する関数を用いる。
def load_yaml_with_path_fix(filepath: str):
    with open(filepath, 'r', encoding='utf-8') as f:
        raw_text = f.read()
    # バックスラッシュをスラッシュに変換（YAML構文エラー防止）
    # ダブルクォートは保持する（パスの一部として必要）
    fixed_text = raw_text.replace("\\", "/")
    # YAMLとして読み込む
    return yaml.safe_load(fixed_text)

# メイン処理
def main():
    if len(sys.argv) < 2:
        print("Usage: python main.py fortran_analyze.cntl")
        sys.exit(1)

    config_path = sys.argv[1]
    config = load_yaml_with_path_fix(config_path)

    # 解析対象のFortranファイルパス
    fortran_file = config['fortran_file']

    # mermaidフロー図の出力ディレクトリ
    output_dir = config['output_dir']

    # 各種出力ファイルのパスを定義（デフォルト値を設定）
    # mmd生成のための中間ファイル (FortranAnalyzerがFortranのコードを解析した内容のまとめ。MermaidGeneratorが読み込むための中間ファイルとする)
    flow_data_file = config.get('flow_data_file', 'flow_data.json')
    # mmd生成のための中間ファイルから、人間が見てFortranファイルの構造が分かるようにしたファイル
    flow_report_file = config.get('flow_report_file', 'flow_report.txt')
    # loggerのファイル名
    log_filename = config.get('log_filename', 'fortran_analyzer.log')
    
    setup_logging(log_filename)

    # ファイルの存在チェック
    if not os.path.exists(fortran_file):
        logging.error(f"入力ファイルが見つかりません: {fortran_file}")
        print(f"エラー: 入力ファイル '{fortran_file}' が見つかりません。パスを確認してください。")
        return
    # 出力ディレクトリが存在しない場合は作成
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        logging.info(f"出力ディレクトリを作成しました: {output_dir}")

    logging.info(f"Fortranソースコード解析を開始します: {fortran_file}")
    analyzer = FortranAnalyzer()
    
    # ファイルの読み込みは japanese_encoding.py の detect_encoding_and_read_file 関数で行う
    lines, encoding = detect_encoding_and_read_file(fortran_file)
    if lines is None:
        logging.error(f"ファイルの読み込みに失敗しました: {fortran_file}, encoding={encoding}")
        return

    analysis_result = analyzer.analyze(lines)

    if analysis_result:
        logging.info("\n" + "\n" + "="*50 + "\n Fortran Code Analyzer - Summary\n" + "="*50)
        
        # 解析状況ファイルを生成
        logging.info(f"flow_data.json の生成を開始します: {flow_data_file}")
        analyzer.export_analysis_data(flow_data_file)
        logging.info(f"flow_data.json の生成が完了しました: {flow_data_file}")
        # ネストレベル付きテキストレポートを生成
        logging.info(f"flow_report.txt の生成を開始します: {flow_report_file}")
        analyzer._generate_flow_report(flow_report_file)
        logging.info(f"flow_report.txt の生成が完了しました: {flow_report_file}")
        # 解析結果の概要を出力
        with open(flow_data_file, encoding='utf-8') as f:
            data = json.load(f)
        for unit_name, unit in [(u.get('name', ''), u) for u in data['units']]:
            calls = [a['target'] for a in unit['statements'] if a.get('type') == 'CALL']
            includes = [a['target'] for a in unit['statements'] if a.get('type') == 'INCLUDE']
            summary = (f"ユニット番号: {unit.get('id', 'N/A'):<3} | "
                       f"   - {unit_name:<20} | "
                       f"Type: {unit.get('type', 'N/A'):<15} | "
                       f"CALLs: {len(calls):<2} | "
                       f"INCLUDEs: {len(includes):<2} | "
                       f"Lines: {unit.get('start_line', 'N/A')}-{unit.get('end_line', 'N/A')}")
            logging.info(summary)
        
        # Mermaidチャートを生成 (flow_data.jsonを読み込むように変更)
        logging.info("\n" + "\n" + "Mermaidフローチャートの生成を開始します。出力先: {output_dir}")
        mermaid_gen = MermaidGenerator(flow_data_file, output_dir) # JSONファイルパスを渡す
        mermaid_gen.generate_flowcharts(fortran_file) 
        #mermaid_gen.generate_unit_flowchart(fortran_file)

        logging.info(f"\n解析ログは 'fortran_analyzer.log' に、")
        logging.info(f"Mermaidチャートは '{output_dir}' フォルダに保存されました。")
        #print(f"\n解析ログは 'fortran_analyzer.log' に、")
        #print(f"Mermaidチャートは '{output_dir}' フォルダに保存されました。")
    else:
        logging.error("Fortranソースコードの解析に失敗しました。詳細についてはログファイルを参照。")
        #print("エラー: ソースコードの解析に失敗しました。ログファイルで詳細を確認してください。")

if __name__ == "__main__":
    main()